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

# --- 1. 連接 Google Sheets (每次呼叫都重新連線，確保不斷線) ---
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

# --- 2. 使用者分頁管理 ---
def get_user_sheet_with_auth(spreadsheet, user_id, pin_code, login_mode=True):
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    if not safe_id: return None, "ID 無效"
    
    try:
        # A. 嘗試取得既有分頁
        sheet = spreadsheet.worksheet(safe_id)
        saved_pin = sheet.acell('Z1').value # 讀取藏在 Z1 的密碼
        
        # 驗證密碼 (如果 Z1 空的就放行，相容舊資料)
        if saved_pin and str(saved_pin) != str(pin_code):
            return None, "🔒 密碼錯誤！無法存取此清單。"
        
        return sheet, "Success"

    except gspread.WorksheetNotFound:
        # B. 建立新分頁 (如果是登入模式卻找不到，代表帳號不存在)
        if login_mode:
             # 但為了方便體驗，我們這裡採用「找不到就自動註冊」的邏輯
             pass 
             
        try:
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=100, cols=26)
            sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
            sheet.update_acell('Z1', str(pin_code)) # 儲存密碼
            return sheet, "Success"
        except Exception as e:
            return None, f"建立失敗: {e}"

# --- 3. 資料同步功能 (將編輯後的 DataFrame 存回 Google Sheet) ---
def save_dataframe_to_sheet(sheet, df, pin_code):
    try:
        # 1. 先把密碼 (PIN) 備份起來 (因為 clear 會清空整張表)
        # 也可以直接用參數傳進來的 pin_code，確保不會遺失
        
        # 2. 清空工作表
        sheet.clear()
        
        # 3. 準備寫入的資料 (包含標題列)
        # Google Sheet 需要 list of lists 格式
        data_to_write = [df.columns.values.tolist()] + df.values.tolist()
        
        # 4. 寫入資料
        sheet.update(data_to_write)
        
        # 5. 把密碼寫回 Z1 (重要！不然下次會登不進去)
        sheet.update_acell('Z1', str(pin_code))
        
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 4. 工具函式 ---
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

# --- 5. 側邊欄：登入系統 ---
st.sidebar.title("🔐 用戶登入")

# 初始化 session state
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False

# 登入介面
if not st.session_state.is_logged_in:
    st.sidebar.info("輸入暱稱與密碼 (PIN) 即可登入或註冊。")
    with st.sidebar.form("login_form"):
        input_id = st.text_input("👤 暱稱 / ID", placeholder="例如: Kevin_List")
        input_pin = st.text_input("🔑 密碼 (PIN)", type="password", placeholder="例如: 1234")
        login_submitted = st.form_submit_button("🚀 登入 / 註冊")
    
    if login_submitted:
        if input_id and input_pin:
            # 登入當下測試連線
            ss = connect_to_spreadsheet()
            if ss:
                sheet, msg = get_user_sheet_with_auth(ss, input_id, input_pin)
                if sheet:
                    # 登入成功！只存 ID 和 PIN，不存 sheet 物件 (避免斷線錯誤)
                    st.session_state.user_id = input_id
                    st.session_state.user_pin = input_pin
                    st.session_state.is_logged_in = True
                    st.rerun()
                else:
                    st.sidebar.error(msg)
            else:
                st.sidebar.error("無法連接資料庫")
        else:
            st.sidebar.warning("請輸入完整資訊")

    st.title("👋 歡迎來到 2026 書展採購助手")
    st.markdown("### 👈 請先在左側登入")
    st.info("💡 每個 ID 擁有獨立的雲端清單，輸入密碼保護您的隱私。")
    st.stop()

# --- 登入後的狀態列 ---
st.sidebar.success(f"✅ 已登入：{st.session_state.user_id}")
if st.sidebar.button("登出"):
    st.session_state.is_logged_in = False
    st.session_state.user_id = ""
    st.session_state.user_pin = ""
    st.rerun()

# --- 主程式：建立連線 ---
# 每次 Rerun 都重新連線，解決 "讀取錯誤" 的問題
spreadsheet = connect_to_spreadsheet()
if not spreadsheet:
    st.error("❌ 連線失敗，請檢查網路或重新整理。")
    st.stop()

# 取得 Sheet (使用 Session 中的 ID)
user_sheet, _ = get_user_sheet_with_auth(spreadsheet, st.session_state.user_id, st.session_state.user_pin)
if not user_sheet:
    st.error("❌ 找不到資料表，請重新登入。")
    st.session_state.is_logged_in = False
    st.stop()

st.title(f"🛒 {st.session_state.user_id} 的採購清單")
st.markdown("---")

# --- A 區：掃描與新增 ---
if 'manual_entry_mode' not in st.session_state: st.session_state.manual_entry_mode = False
if 'search_result' not in st.session_state: st.session_state.search_result = None

with st.expander("🔍 **新增書籍 (點此展開/收合)**", expanded=True):
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("isbn_form", clear_on_submit=False): 
            isbn_input = st.text_input("ISBN 條碼")
            submitted = st.form_submit_button("🔍 查詢")

        if submitted and isbn_input:
            with st.spinner("☁️ 搜尋中..."):
                res = smart_book_search(isbn_input)
                st.session_state.search_result = res

    if st.session_state.search_result:
        res = st.session_state.search_result
        if res['found']: st.success(f"✅ 找到：{res['書名']}")
        else: st.warning("⚠️ 無資料，請手動填寫。")

        with st.form("confirm_form"):
            c1, c2 = st.columns([1, 2])
            with c1:
                if res['封面']: st.image(res['封面'], width=100)
                else: st.text("(無封面)")
                
                clean_isbn_val = clean_isbn_func(res['ISBN'])
                st.markdown("👇 **查價傳送門**")
                st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{clean_isbn_val}" target="_blank">博客來</a>｜<a href="https://findbook.tw/book/{clean_isbn_val}/price" target="_blank">Findbook</a>''', unsafe_allow_html=True)

            with c2:
                new_title = st.text_input("書名", value=res['書名'])
                new_author = st.text_input("作者", value=res['作者'])
                price_val = res['定價'] if res['定價'] else ""
                new_price = st.text_input("💰 價格", value=price_val)
                
                confirm_btn = st.form_submit_button("✅ 加入清單")

                if confirm_btn:
                    new_row = [res['建檔時間'], new_title, new_author, res['ISBN'], new_price, "待購"]
                    user_sheet.append_row(new_row)
                    st.toast(f"🎉 已加入：{new_title}")
                    time.sleep(0.5)
                    st.session_state.search_result = None
                    st.rerun()

st.divider()

# --- B 區：即時編輯清單 (重點功能) ---
st.subheader(f"📋 管理我的清單 ({st.session_state.user_id})")

try:
    # 1. 讀取資料
    records = user_sheet.get_all_records()
    
    # 2. 轉成 DataFrame 讓使用者編輯
    # 如果是空的，建立一個空的 DataFrame 結構
    if records:
        df = pd.DataFrame(records)
    else:
        df = pd.DataFrame(columns=["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])

    # 3. 顯示編輯器 (num_rows="dynamic" 允許新增/刪除行)
    edited_df = st.data_editor(
        df, 
        use_container_width=True, 
        num_rows="dynamic", 
        key="data_editor",
        column_config={
            "封面": st.column_config.ImageColumn("封面"), # 如果有封面欄位可以顯示圖
            "價格": st.column_config.NumberColumn("價格", format="$%d"),
            "狀態": st.column_config.SelectboxColumn("狀態", options=["待購", "已購", "猶豫中", "放棄"])
        }
    )

    # 4. 儲存按鈕
    col_save, col_info = st.columns([1, 4])
    with col_save:
        if st.button("💾 儲存所有變更", type="primary"):
            with st.spinner("正在同步回雲端..."):
                # 呼叫儲存函式
                success = save_dataframe_to_sheet(user_sheet, edited_df, st.session_state.user_pin)
                if success:
                    st.success("✅ 儲存成功！")
                    time.sleep(1)
                    st.rerun()
    with col_info:
        if not df.equals(edited_df):
            st.warning("⚠️ 您有未儲存的修改，請記得按左側「儲存」按鈕！")

except Exception as e:
    st.error(f"讀取清單失敗: {e}")
    # 有時候是因為標題列被刪掉了，這裡提供一個修復按鈕
    if st.button("🛠️ 修復表格結構"):
        user_sheet.clear()
        user_sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
        user_sheet.update_acell('Z1', str(st.session_state.user_pin))
        st.rerun()