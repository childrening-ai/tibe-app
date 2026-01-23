import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import datetime
import time
import re
import urllib3

# 設定頁面
st.set_page_config(page_title="掃碼購物車", page_icon="🛒", layout="wide")

# --- 設定區 ---
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 連接 Google Sheets ---
@st.cache_resource
def connect_to_spreadsheet():
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
        spreadsheet = client.open(SHEET_NAME)
        return spreadsheet
    except Exception as e:
        return None

# --- 2. 使用者分頁管理 (含密碼驗證) ---
def get_user_sheet_with_auth(spreadsheet, user_id, pin_code):
    """
    邏輯：
    1. 嘗試找分頁。
    2. 如果找不到 -> 建立新分頁 -> 將 PIN 碼寫入 Z1 儲存格 (藏起來) -> 回傳成功。
    3. 如果找到了 -> 讀取 Z1 的 PIN 碼 -> 比對輸入的 PIN -> 成功或失敗。
    """
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    if not safe_id: return None, "ID 無效"
    
    try:
        # A. 嘗試取得既有分頁 (登入模式)
        sheet = spreadsheet.worksheet(safe_id)
        
        # 讀取儲存在 Z1 格子的密碼
        saved_pin = sheet.acell('Z1').value
        
        # 為了相容舊資料，如果 Z1 沒密碼，就直接放行；如果有密碼，就要檢查
        if saved_pin and str(saved_pin) != str(pin_code):
            return None, "🔒 密碼錯誤！這不是您的清單嗎？"
        
        return sheet, "Success"

    except gspread.WorksheetNotFound:
        # B. 建立新分頁 (註冊模式)
        try:
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=100, cols=26)
            # 建立標題列
            sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
            # 🔥 將密碼儲存在 Z1 (很遠的格子，當作資料庫用)
            sheet.update_acell('Z1', str(pin_code))
            return sheet, "Success"
        except Exception as e:
            return None, f"建立失敗: {e}"

# --- 3. 工具函式 ---
def clean_isbn_func(isbn_raw):
    if not isbn_raw: return ""
    return str(isbn_raw).strip().replace("-", "").replace(" ", "").replace("\n", "").replace("\t", "")

def search_google_books(isbn):
    clean_isbn = clean_isbn_func(isbn)
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    try:
        res = requests.get(url, timeout=3).json()
        if "items" in res:
            info = res["items"][0]["volumeInfo"]
            return {
                "書名": info.get("title", ""),
                "作者": ", ".join(info.get("authors", [])),
                "封面": info.get("imageLinks", {}).get("thumbnail", ""),
                "found": True
            }
    except: pass
    return {"found": False}

def smart_book_search(isbn_input):
    if not isbn_input: return None
    clean_isbn = clean_isbn_func(isbn_input)
    result = {
        "書名": "", "作者": "", "ISBN": clean_isbn, 
        "封面": "", "定價": "", 
        "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found": False
    }
    g_data = search_google_books(clean_isbn)
    if g_data["found"]:
        result.update(g_data)
        result["found"] = True
    return result

# --- 4. 側邊欄：登入系統 (改良版) ---
st.sidebar.title("🔐 用戶登入")

if "user_sheet" not in st.session_state:
    st.session_state.user_sheet = None
if "user_id" not in st.session_state:
    st.session_state.user_id = ""

# 如果還沒登入成功
if st.session_state.user_sheet is None:
    st.sidebar.info("輸入暱稱與密碼，系統會自動判斷是「登入」還是「註冊」。")
    
    with st.sidebar.form("login_form"):
        input_id = st.text_input("👤 暱稱 / ID", placeholder="例如: Kevin_List")
        input_pin = st.text_input("🔑 設定或輸入密碼 (PIN)", type="password", placeholder="例如: 1234")
        login_submitted = st.form_submit_button("🚀 登入 / 註冊")
    
    if login_submitted:
        if input_id and input_pin:
            with st.spinner("連線中..."):
                spreadsheet = connect_to_spreadsheet()
                if spreadsheet:
                    sheet, msg = get_user_sheet_with_auth(spreadsheet, input_id, input_pin)
                    
                    if sheet:
                        st.session_state.user_sheet = sheet # 存物件雖然不推薦但這裡是簡單解
                        st.session_state.user_id = input_id
                        st.session_state.spreadsheet = spreadsheet # 暫存連線物件
                        st.rerun()
                    else:
                        st.sidebar.error(msg)
                else:
                    st.sidebar.error("無法連接資料庫")
        else:
            st.sidebar.warning("請輸入暱稱和密碼")

    st.title("👋 歡迎來到 2026 書展採購助手")
    st.markdown("### 👈 請先在左側登入")
    st.info("💡 如果您是第一次來，輸入喜歡的暱稱和密碼，系統會自動為您建立帳號。")
    st.stop() # 停止執行後續程式

# --- 登入成功後顯示側邊欄資訊 ---
st.sidebar.success(f"✅ 已登入：{st.session_state.user_id}")
if st.sidebar.button("登出"):
    st.session_state.user_sheet = None
    st.session_state.user_id = ""
    st.rerun()

# --- 主程式 (登入後) ---
# 重新抓取 sheet 物件以防 session 過期 (或是直接用 session 裡的)
user_sheet = st.session_state.user_sheet
user_id = st.session_state.user_id

st.title(f"🛒 {user_id} 的採購清單")
st.markdown("---")

# --- 掃描與查詢區 ---
if 'manual_entry_mode' not in st.session_state: st.session_state.manual_entry_mode = False
if 'search_result' not in st.session_state: st.session_state.search_result = None

col1, col2 = st.columns([1, 2])
with col1:
    st.info("👇 輸入 ISBN")
    with st.form("isbn_form", clear_on_submit=False): 
        isbn_input = st.text_input("ISBN 條碼")
        submitted = st.form_submit_button("🔍 查詢")

    if submitted and isbn_input:
        with st.spinner("☁️ 搜尋中..."):
            res = smart_book_search(isbn_input)
            st.session_state.search_result = res
            st.session_state.manual_entry_mode = False 

if st.session_state.search_result:
    res = st.session_state.search_result
    st.divider()
    
    if res['found']: st.success(f"✅ 找到書籍：{res['書名']}")
    else: st.warning("⚠️ 資料庫無資料，請手動填寫。")

    with st.form("confirm_form"):
        c1, c2 = st.columns([1, 2])
        with c1:
            if res['封面']: st.image(res['封面'], width=120)
            else: st.markdown("🖼️ (無封面)")
            
            clean_isbn_val = clean_isbn_func(res['ISBN'])
            books_link = f"https://search.books.com.tw/search/query/key/{clean_isbn_val}"
            findbook_link = f"https://findbook.tw/book/{clean_isbn_val}/price"

            st.markdown("---")
            st.caption("👇 快速查價連結")
            st.markdown(f'''
                <a href="{books_link}" target="_blank" style="text-decoration:none;"><button style="width:100%;padding:5px;cursor:pointer;">🔍 查博客來</button></a>
                <br><br>
                <a href="{findbook_link}" target="_blank" style="text-decoration:none;"><button style="width:100%;padding:5px;cursor:pointer;">🔍 查 Findbook</button></a>
            ''', unsafe_allow_html=True)

        with c2:
            new_title = st.text_input("書名", value=res['書名'])
            new_author = st.text_input("作者", value=res['作者'])
            price_val = res['定價'] if res['定價'] else ""
            new_price = st.text_input("💰 價格 (請依查價結果填入)", value=price_val)
            
            confirm_btn = st.form_submit_button("✅ 加入我的清單")

            if confirm_btn:
                new_row = [res['建檔時間'], new_title, new_author, res['ISBN'], new_price, "待購"]
                user_sheet.append_row(new_row)
                st.toast(f"🎉 已加入您的清單：{new_title}")
                time.sleep(1)
                st.session_state.search_result = None
                st.rerun()

# --- 清單顯示區 ---
st.divider()
st.subheader(f"📋 {user_id} 的雲端清單")
try:
    records = user_sheet.get_all_records()
    if records:
        df = pd.DataFrame(records)
        st.data_editor(df, use_container_width=True, num_rows="dynamic", key="data_editor")
    else:
        st.info("您的清單目前是空的，快去掃幾本書吧！")
except Exception as e:
    st.error("讀取清單時發生錯誤，請嘗試重新登入。")