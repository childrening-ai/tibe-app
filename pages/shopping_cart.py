import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
import datetime
import time
import re

# 設定頁面
st.set_page_config(page_title="掃碼購物車", page_icon="🛒", layout="wide")

st.title("🛒 2026 書展掃碼比價 & 採購清單")
st.markdown("輸入 ISBN，自動抓取 **國家圖書館** 與 **Google** 資料，建立最精準的採購清單！")

# --- 設定區 ---
# 🔥 更新年份：請確保 Google Drive 裡的試算表名稱跟這裡一模一樣
SHEET_NAME = "2026國際書展採購清單"

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

# --- 2. 爬蟲：國家圖書館 (NCL) - 依據截圖優化版 ---
def search_ncl(isbn):
    """
    策略優化：
    Level 1 (列表頁): 抓取 封面(Base64), 書名, 作者, 出版者, 詳細頁連結
    Level 2 (詳細頁): 專門抓取 "定價"
    """
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    base_url = "https://isbn.ncl.edu.tw/NEW_ISBNNet/"
    search_url = f"{base_url}H30_SearchBooks.php"
    
    session = requests.Session()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    
    result = {
        "source": "NCL",
        "書名": "", "作者": "", "出版社": "", "ISBN": clean_isbn,
        "定價": "", "封面": ""
    }

    try:
        # [Step 1] 搜尋列表頁 (Level 1)
        params = {
            "FO_SearchValue0": clean_isbn,
            "FO_SearchField0": "ISBN",
            "Pact": "DisplayAll4Simple",
        }
        res1 = session.get(search_url, params=params, headers=headers, timeout=10)
        res1.encoding = 'utf-8'
        soup1 = BeautifulSoup(res1.text, 'html.parser')
        
        # 根據您的截圖，資料在 <table class="table-searchbooks"> 裡面
        # 我們直接找含有 data-th 屬性的 td，這樣最準
        
        # 1. 抓連結與書名 (data-th="書名")
        title_td = soup1.find("td", {"data-th": "書名"})
        detail_link = ""
        
        if title_td:
            link_tag = title_td.find("a")
            if link_tag:
                result["書名"] = link_tag.text.strip()
                detail_link = link_tag['href']
            else:
                result["書名"] = title_td.text.strip() # 萬一沒連結
        else:
            return None # 連書名都沒找到，代表沒這本書
            
        # 2. 抓封面圖片 (data-th="封面圖") - Base64
        img_td = soup1.find("td", {"data-th": "封面圖"}) 
        if img_td:
            img_tag = img_td.find("img")
            if img_tag and 'src' in img_tag.attrs:
                result["封面"] = img_tag['src'] # 抓到那串長長的 Base64

        # 3. 抓作者 (data-th="作者")
        author_td = soup1.find("td", {"data-th": "作者"})
        if author_td:
            result["作者"] = author_td.text.strip()

        # 4. 抓出版者 (data-th="出版者")
        pub_td = soup1.find("td", {"data-th": "出版者"})
        if pub_td:
            result["出版社"] = pub_td.text.strip()

        # [Step 2] 進入詳細頁 (Level 2) - 只為了抓價格
        if detail_link:
            try:
                target_url = base_url + detail_link
                res2 = session.get(target_url, headers=headers, timeout=5) # 這裡給短一點時間，失敗就算了
                res2.encoding = 'utf-8'
                soup2 = BeautifulSoup(res2.text, 'html.parser')
                
                # 抓定價 (data-th="定價")
                price_td = soup2.find("td", {"data-th": "定價"})
                if price_td:
                    raw_price = price_td.text.strip()
                    # 清洗價格 (把 NT$ 拿掉，只留數字)
                    result["定價"] = re.sub(r"[^\d]", "", raw_price)
            except:
                print("Level 2 抓價格失敗，但不影響基本資料")

        return result

    except Exception as e:
        print(f"NCL 爬蟲錯誤: {e}")
        return None

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
    
    # 預設結果容器
    final_result = {
        "書名": "", "作者": "", "ISBN": clean_isbn, 
        "封面": "", "定價": "",
        "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found": False
    }

    # A. 先問 Google (當作備案)
    google_data = search_google_books(clean_isbn)
    if google_data:
        final_result["封面"] = google_data["封面"]
        final_result["書名"] = google_data["書名"]
        final_result["作者"] = google_data["作者"]
        final_result["found"] = True

    # B. 再問國圖 (主力 - 依據截圖優化)
    ncl_data = search_ncl(clean_isbn)
    if ncl_data:
        # 國圖文字資訊最準，覆蓋 Google
        final_result["書名"] = ncl_data["書名"]
        if ncl_data["出版社"]: 
            final_result["書名"] = f"{ncl_data['書名']} ({ncl_data['出版社']})"
        
        if ncl_data["作者"]: 
            final_result["作者"] = ncl_data["作者"]
            
        if ncl_data["定價"]: 
            final_result["定價"] = ncl_data["定價"]
        
        # 🔥 重點：如果國圖有圖片 (Base64)，優先使用！
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
                
                # 顯示圖片 (支援 Google 網址 或 國圖 Base64)
                if book_data['封面']:
                    st.image(book_data['封面'], width=120, caption=info_text)
                elif info_text:
                    st.info(info_text)

                # 準備寫入 Excel
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