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

# --- 2. 爬蟲：國家圖書館 (NCL) - 略過 SSL 驗證版 ---
def search_ncl(isbn):
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    base_url = "https://isbn.ncl.edu.tw/NEW_ISBNNet/"
    search_url = f"{base_url}H30_SearchBooks.php"
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://isbn.ncl.edu.tw/NEW_ISBNNet/H30_SearchBooks.php' 
    }
    
    result = {
        "source": "NCL",
        "書名": "", "作者": "", "出版社": "", "ISBN": clean_isbn,
        "定價": "", "封面": ""
    }

    try:
        # [Step 1] 搜尋列表頁
        params = {
            "FO_SearchValue0": clean_isbn,
            "FO_SearchField0": "ISBN",
            "Pact": "DisplayAll4Simple",
        }
        
        # 🔥 關鍵修改：verify=False (略過 SSL 檢查)
        res1 = session.get(search_url, params=params, headers=headers, timeout=15, verify=False)
        res1.encoding = 'utf-8'
        
        if res1.status_code != 200:
            print(f"❌ 國圖連線失敗，狀態碼: {res1.status_code}")
            return None
            
        soup1 = BeautifulSoup(res1.text, 'html.parser')
        
        # --- 抓取邏輯 (維持原本針對截圖優化的版本) ---
        title_td = soup1.find("td", {"data-th": "書名"})
        detail_link = ""
        
        if title_td:
            link_tag = title_td.find("a")
            if link_tag:
                result["書名"] = link_tag.text.strip()
                detail_link = link_tag['href']
            else:
                result["書名"] = title_td.text.strip()
            
            img_td = soup1.find("td", {"data-th": "封面圖"})
            if img_td:
                img_tag = img_td.find("img")
                if img_tag and 'src' in img_tag.attrs:
                    result["封面"] = img_tag['src']

            author_td = soup1.find("td", {"data-th": "作者"})
            if author_td: result["作者"] = author_td.text.strip()

            pub_td = soup1.find("td", {"data-th": "出版者"})
            if pub_td: result["出版社"] = pub_td.text.strip()

        else:
            # Fallback: 暴力找連結
            link_tag = soup1.find("a", href=re.compile(r"main_DisplayRecord\.php"))
            if link_tag:
                result["書名"] = link_tag.text.strip()
                detail_link = link_tag['href']
            else:
                return None

        # [Step 2] 進入詳細頁 (為了抓定價)
        if detail_link:
            try:
                target_url = base_url + detail_link
                # 🔥 關鍵修改：這裡也要 verify=False
                res2 = session.get(target_url, headers=headers, timeout=10, verify=False)
                res2.encoding = 'utf-8'
                soup2 = BeautifulSoup(res2.text, 'html.parser')
                
                price_td = soup2.find("td", {"data-th": "定價"})
                if price_td:
                    raw_price = price_td.text.strip()
                    result["定價"] = re.sub(r"[^\d]", "", raw_price)
            except:
                pass

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