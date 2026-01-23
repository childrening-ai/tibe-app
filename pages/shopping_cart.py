import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
import datetime
import time
import re
import urllib3 # 引入這個來關閉警告

# 設定頁面
st.set_page_config(page_title="掃碼購物車", page_icon="🛒", layout="wide")

st.title("🛒 2026 書展掃碼比價 & 採購清單")
st.markdown("輸入 ISBN，自動抓取 **國家圖書館** 與 **Google** 資料，建立最精準的採購清單！")

# --- 設定區 ---
# 🔥 請確認 Google Sheet 名稱正確
SHEET_NAME = "2026國際書展採購清單"

# 🤫 關閉 "InsecureRequestWarning" 警告 (因為我們要略過 SSL 檢查)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 連接 Google Sheets ---
@st.cache_resource
def connect_to_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            if "private_key" in creds_dict:
                 creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("secrets.json", scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        print(f"連線錯誤: {e}")
        return None

# --- 新增：改爬 Findbook (借力使力版) ---
def search_findbook(isbn):
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    # Findbook 的網址規則
    url = f"https://findbook.com.tw/{clean_isbn}"
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://findbook.com.tw/'
    }
    
    try:
        # 嘗試連線
        res = session.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        result = {
            "source": "Findbook",
            "書名": "", "作者": "", "定價": "", "封面": "", "Link": url
        }
        
        # 1. 抓書名 (通常在 h1 或 h2)
        # Findbook 的結構通常標題會有 itemprop="name"
        title_tag = soup.find("span", {"itemprop": "name"})
        if title_tag:
            result["書名"] = title_tag.text.strip()
            
        # 2. 抓作者
        author_tag = soup.find("span", {"itemprop": "author"})
        if author_tag:
            result["作者"] = author_tag.text.strip()
            
        # 3. 抓圖片
        img_tag = soup.find("img", {"itemprop": "image"})
        if img_tag and 'src' in img_tag.attrs:
            result["封面"] = img_tag['src']
            
        # 4. 🔥 抓價格 (這是重點！)
        # Findbook 會有一個比價列表，我們抓第一個（通常是最便宜或主打）
        # 尋找 class="price" 的標籤
        price_tags = soup.find_all(class_="price")
        if price_tags:
            # 濾掉非數字的文字，只留價格
            for p in price_tags:
                p_text = p.text.strip()
                # 排除 "比價" 這種標題字，找含有數字的
                if any(char.isdigit() for char in p_text):
                    # 取出數字
                    clean_price = re.sub(r"[^\d]", "", p_text)
                    if clean_price:
                        result["定價"] = clean_price
                        break # 抓到一個就收工

        return result

    except Exception as e:
        print(f"Findbook 爬取失敗: {e}")
        return None

# --- 修改 smart_book_search 整合邏輯 ---
def smart_book_search(isbn):
    if not isbn: return None
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    
    final = {
        "書名": "", "作者": "", "ISBN": clean_isbn, 
        "封面": "", "定價": "", 
        "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found": False
    }

    # 1. 策略 A: 先問 Findbook (因為它有價格！)
    fb_data = search_findbook(clean_isbn)
    if fb_data and fb_data["書名"]:
        final.update(fb_data)
        final["found"] = True
    
    # 2. 策略 B: 如果 Findbook 沒抓到 (可能被擋)，再問 Google Books 補救
    # (如果 Findbook 已經抓到書名，這裡就不跑了，節省資源)
    if not final["found"] or not final["封面"]:
        g_data = search_google_books(clean_isbn)
        if g_data:
            # 如果 Findbook 沒書名，用 Google 的
            if not final["書名"]: final["書名"] = g_data["書名"]
            if not final["作者"]: final["作者"] = g_data["作者"]
            # 如果 Findbook 沒圖片，用 Google 的 (Google圖片通常比較好拿)
            if not final["封面"]: final["封面"] = g_data["封面"]
            final["found"] = True

    return final

# --- 3. 輔助：Google Books ---
def search_google_books(isbn):
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    try:
        res = requests.get(url).json()
        if "items" in res:
            info = res["items"][0]["volumeInfo"]
            return {
                "source": "Google",
                "書名": info.get("title", ""),
                "作者": ", ".join(info.get("authors", [])),
                "封面": info.get("imageLinks", {}).get("thumbnail", "")
            }
    except:
        pass
    return None

# --- 4. 整合查詢邏輯 ---
def smart_book_search(isbn):
    if not isbn: return None
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    
    final_result = {
        "書名": "", "作者": "", "ISBN": clean_isbn, 
        "封面": "", "定價": "",
        "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found": False
    }

    # A. 先問 Google
    google_data = search_google_books(clean_isbn)
    if google_data:
        final_result["封面"] = google_data["封面"]
        final_result["書名"] = google_data["書名"]
        final_result["作者"] = google_data["作者"]
        final_result["found"] = True

    # B. 再問國圖 (主力)
    ncl_data = search_ncl(clean_isbn)
    if ncl_data:
        final_result["書名"] = ncl_data["書名"]
        if ncl_data["出版社"]: 
            final_result["書名"] = f"{ncl_data['書名']} ({ncl_data['出版社']})"
        if ncl_data["作者"]: 
            final_result["作者"] = ncl_data["作者"]
        if ncl_data["定價"]: 
            final_result["定價"] = ncl_data["定價"]
        if ncl_data["封面"]:
            final_result["封面"] = ncl_data["封面"]
        final_result["found"] = True
    
    return final_result

# --- 主程式介面 ---
sheet = connect_to_sheet()

if not sheet:
    st.error(f"❌ 無法連接試算表！請檢查設定：\n1. Google Drive 檔案名稱是否為 `{SHEET_NAME}`\n2. Secrets 是否設定正確")
    st.stop()

if 'manual_entry_mode' not in st.session_state:
    st.session_state.manual_entry_mode = False
if 'last_isbn' not in st.session_state:
    st.session_state.last_isbn = ""

col1, col2 = st.columns([1, 2])

with col1:
    st.info("👇 在此輸入 ISBN")
    with st.form("isbn_form", clear_on_submit=True):
        isbn_input = st.text_input("ISBN 條碼", placeholder="支援國圖查詢...")
        submitted = st.form_submit_button("🔍 查詢與加入")

    if submitted and isbn_input:
        with st.spinner("🔍 正在連線國家圖書館 & Google..."):
            book_data = smart_book_search(isbn_input)
            
            if book_data['found']:
                st.success(f"已找到：{book_data['書名']}")
                
                info_text = ""
                if book_data['定價']:
                    info_text += f"💰 定價: ${book_data['定價']} "
                
                if book_data['封面']:
                    st.image(book_data['封面'], width=120, caption=info_text)
                elif info_text:
                    st.info(info_text)

                save_image_link = book_data['封面']
                if save_image_link.startswith("data:image"):
                    save_image_link = "國圖封面(Base64不存入)"

                new_row = [
                    book_data['建檔時間'], 
                    book_data['書名'], 
                    book_data['作者'], 
                    book_data['ISBN'], 
                    book_data['定價'],
                    "待購"
                ]
                sheet.append_row(new_row)
                st.toast("✅ 已成功加入清單！")
                time.sleep(1)
                st.rerun()
            
            else:
                st.warning(f"國圖與 Google 都找不到: {isbn_input}")
                st.session_state.manual_entry_mode = True
                st.session_state.last_isbn = isbn_input

    if st.session_state.manual_entry_mode:
        st.markdown("### ✍️ 手動建立檔案")
        with st.form("manual_form"):
            m_title = st.text_input("書名", value="")
            m_author = st.text_input("作者", value="")
            m_price = st.text_input("現場價格", value="")
            
            m_submit = st.form_submit_button("➕ 強制加入清單")
            
            if m_submit:
                if m_title:
                    new_row = [
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        m_title,
                        m_author,
                        st.session_state.last_isbn,
                        m_price,
                        "待購"
                    ]
                    sheet.append_row(new_row)
                    st.success(f"✅ 已手動加入：{m_title}")
                    st.session_state.manual_entry_mode = False
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("請至少輸入書名！")

st.divider()
st.subheader("📋 雲端同步清單")

try:
    records = sheet.get_all_records()
    if records:
        df = pd.DataFrame(records)
        edited_df = st.data_editor(df, use_container_width=True, num_rows="dynamic", key="data_editor")
        st.metric("目前書籍數量", len(df))
    else:
        st.info("目前清單是空的")
        if st.button("🛠️ 建立預設標題列"):
            header = ["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"]
            sheet.append_row(header)
            st.rerun()
except Exception as e:
    st.error(f"讀取資料失敗: {e}")