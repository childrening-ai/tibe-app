import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from bs4 import BeautifulSoup
import datetime
import time
import re
import urllib3

# 設定頁面
st.set_page_config(page_title="掃碼購物車", page_icon="🛒", layout="wide")

st.title("🛒 2026 書展掃碼比價 & 採購清單")
st.markdown("輸入 ISBN，自動抓取 **Findbook (比價網)** 與 **Google** 資料。")

# --- 設定區 ---
SHEET_NAME = "2026國際書展採購清單"
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
        return None

# --- 2. 爬蟲：Findbook 找書網 (主力，有價格) ---
def search_findbook(isbn):
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    url = f"https://findbook.com.tw/{clean_isbn}"
    
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Referer': 'https://findbook.com.tw/'
    }
    
    try:
        # Timeout 設為 10 秒
        res = session.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        result = {
            "source": "Findbook",
            "書名": "", "作者": "", "定價": "", "封面": "", "Link": url
        }
        
        # 抓書名
        title_tag = soup.find("span", {"itemprop": "name"})
        if title_tag:
            result["書名"] = title_tag.text.strip()
            
        # 抓作者
        author_tag = soup.find("span", {"itemprop": "author"})
        if author_tag:
            result["作者"] = author_tag.text.strip()
            
        # 抓圖片
        img_tag = soup.find("img", {"itemprop": "image"})
        if img_tag and 'src' in img_tag.attrs:
            result["封面"] = img_tag['src']
            
        # 抓價格 (Findbook 的比價列表)
        price_tags = soup.find_all(class_="price")
        if price_tags:
            for p in price_tags:
                p_text = p.text.strip()
                # 找含有數字的價格
                if any(char.isdigit() for char in p_text):
                    clean_price = re.sub(r"[^\d]", "", p_text)
                    if clean_price:
                        result["定價"] = clean_price
                        break 

        return result

    except Exception as e:
        print(f"Findbook 爬取失敗: {e}")
        return None

# --- 3. 爬蟲：Google Books (備援，有圖穩) ---
def search_google_books(isbn):
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    try:
        res = requests.get(url, timeout=5).json()
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

# --- 4. 智慧整合邏輯 (已移除 search_ncl) ---
def smart_book_search(isbn):
    if not isbn: return None
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    
    final = {
        "書名": "", "作者": "", "ISBN": clean_isbn, 
        "封面": "", "定價": "", 
        "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found": False
    }

    # 策略 A: 先問 Findbook (因為它可能有價格)
    fb_data = search_findbook(clean_isbn)
    if fb_data and fb_data["書名"]:
        final.update(fb_data)
        final["found"] = True
    
    # 策略 B: 如果 Findbook 失敗或資料不全，問 Google 補強
    if not final["found"] or not final["封面"]:
        g_data = search_google_books(clean_isbn)
        if g_data:
            if not final["書名"]: final["書名"] = g_data["書名"]
            if not final["作者"]: final["作者"] = g_data["作者"]
            if not final["封面"]: final["封面"] = g_data["封面"]
            final["found"] = True

    return final

# --- 主程式 ---
sheet = connect_to_sheet()
if not sheet:
    st.error(f"❌ 無法連接試算表！請檢查 `{SHEET_NAME}` 設定。")
    st.stop()

if 'manual_entry_mode' not in st.session_state:
    st.session_state.manual_entry_mode = False
if 'search_result' not in st.session_state:
    st.session_state.search_result = None

col1, col2 = st.columns([1, 2])

with col1:
    st.info("👇 輸入 ISBN (Findbook/Google)")
    with st.form("isbn_form", clear_on_submit=False): 
        isbn_input = st.text_input("ISBN 條碼")
        submitted = st.form_submit_button("🔍 查詢")

    if submitted and isbn_input:
        with st.spinner("☁️ 雲端搜尋中..."):
            res = smart_book_search(isbn_input)
            st.session_state.search_result = res
            
            if not res['found']:
                st.warning("找不到資料，請手動輸入。")
                st.session_state.manual_entry_mode = True
            else:
                st.session_state.manual_entry_mode = False

# 顯示搜尋結果與確認區
if st.session_state.search_result and not st.session_state.manual_entry_mode:
    res = st.session_state.search_result
    
    st.divider()
    st.markdown("### 📖 確認書籍資料")
    
    # 表單讓使用者補完資料
    with st.form("confirm_form"):
        c1, c2 = st.columns([1, 2])
        with c1:
            if res['封面']:
                st.image(res['封面'], width=100)
            else:
                st.text("無封面")
            
            # 查價傳送門
            st.markdown(f"""
            <a href="https://findbook.tw/book/{res['ISBN']}/price" target="_blank">
                <button style="width:100%; padding:5px; margin:5px 0; cursor:pointer;">🔍 沒抓到價格？點我查價</button>
            </a>
            """, unsafe_allow_html=True)

        with c2:
            new_title = st.text_input("書名", value=res['書名'])
            new_author = st.text_input("作者", value=res['作者'])
            new_price = st.text_input("💰 價格", value=res['定價'])
            
            confirm_btn = st.form_submit_button("✅ 確認並加入清單")

            if confirm_btn:
                save_img = res['封面']
                if save_img.startswith("data:image"): save_img = "Base64圖片"
                
                new_row = [
                    res['建檔時間'], new_title, new_author, res['ISBN'], new_price, "待購"
                ]
                sheet.append_row(new_row)
                st.toast(f"🎉 已加入：{new_title}")
                time.sleep(1)
                st.session_state.search_result = None
                st.rerun()

# 手動輸入模式
if st.session_state.manual_entry_mode:
    st.divider()
    with st.form("manual_form"):
        st.markdown("### ✍️ 手動建立檔案")
        m_title = st.text_input("書名")
        m_author = st.text_input("作者")
        m_isbn = st.text_input("ISBN", value=isbn_input)
        m_price = st.text_input("價格")
        m_submit = st.form_submit_button("➕ 加入")
        
        if m_submit and m_title:
            sheet.append_row([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                m_title, m_author, m_isbn, m_price, "待購"
            ])
            st.success("已手動加入！")
            st.session_state.manual_entry_mode = False
            st.rerun()

st.divider()
st.subheader("📋 雲端同步清單")
try:
    records = sheet.get_all_records()
    if records:
        st.data_editor(pd.DataFrame(records), use_container_width=True, num_rows="dynamic")
    else:
        st.info("清單是空的")
        if st.button("建立標題列"):
            sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
            st.rerun()
except:
    pass