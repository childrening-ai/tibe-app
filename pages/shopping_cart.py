import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import datetime
import time
import re
import urllib3

st.set_page_config(page_title="書展敗家計算機", page_icon="💸", layout="wide")

# --- 設定區 ---
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 連接 Google Sheets ---
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
        sheet = spreadsheet.worksheet(safe_id)
        saved_pin = sheet.acell('Z1').value
        if saved_pin and str(saved_pin).strip() != str(pin_code).strip():
            return None, "🔒 密碼錯誤！"
        return sheet, "Success"
    except gspread.WorksheetNotFound:
        try:
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=100, cols=26)
            # 建立時先給標題
            sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
            sheet.update_acell('Z1', str(pin_code))
            return sheet, "Success"
        except Exception:
            return None, "建立失敗"

# --- 3. 資料讀取 (🔥 強制補齊空位，解決空白行問題) ---
def load_data_safe(sheet):
    try:
        all_values = sheet.get_all_values()
        
        # 定義標準欄位
        columns = ["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"]
        expected_len = len(columns)

        if len(all_values) <= 1:
            return pd.DataFrame(columns=columns)
        
        # 略過第一列標題
        raw_data = all_values[1:]
        clean_data = []

        for row in raw_data:
            # 1. 確保每一列都是 List (防呆)
            if not isinstance(row, list): continue
            
            # 2. 如果長度不夠，補上空字串
            if len(row) < expected_len:
                row = row + [""] * (expected_len - len(row))
            
            # 3. 如果長度太長，切掉後面的 (只取前6個)
            clean_data.append(row[:expected_len])
        
        df = pd.DataFrame(clean_data, columns=columns)
        return df
    except Exception as e:
        st.error(f"資料讀取異常: {e}")
        return pd.DataFrame(columns=["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])

# --- 4. 資料儲存 (🔥 處理 NaN 避免寫入錯誤) ---
def save_dataframe_to_sheet(sheet, df, pin_code):
    try:
        # 將 NaN 轉為空字串，Google Sheet 才看得懂
        df = df.fillna("")
        
        # 準備資料
        data_to_write = [df.columns.values.tolist()] + df.values.tolist()
        
        # 更新範圍 (A1 到 F + 行數)
        num_rows = len(data_to_write)
        range_str = f"A1:F{num_rows}"
        
        sheet.update(range_name=range_str, values=data_to_write)
        sheet.update_acell('Z1', str(pin_code)) # 確保密碼不見
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 5. 爬蟲工具 ---
def clean_isbn_func(isbn_raw):
    return str(isbn_raw).strip().replace("-", "").replace(" ", "").replace("\n", "").replace("\t", "") if isbn_raw else ""

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
    result = {"書名": "", "作者": "", "ISBN": clean_isbn, "封面": "", "定價": "", "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "found": False}
    g_data = search_google_books(clean_isbn)
    if g_data["found"]:
        result.update(g_data)
        result["found"] = True
    return result

# --- 6. 側邊欄：登入與預算 ---
st.sidebar.title("🔐 用戶登入")

if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "budget" not in st.session_state: st.session_state.budget = 3000

if not st.session_state.is_logged_in:
    st.sidebar.info("登入以管理您的採購清單")
    with st.sidebar.form("login_form"):
        input_id = st.text_input("👤 暱稱", placeholder="例如: Allen")
        input_pin = st.text_input("🔑 PIN碼", type="password")
        if st.form_submit_button("🚀 開始"):
            if input_id and input_pin:
                ss = connect_to_spreadsheet()
                if ss:
                    sheet, msg = get_user_sheet_with_auth(ss, input_id, input_pin)
                    if sheet:
                        st.session_state.user_id = input_id
                        st.session_state.user_pin = input_pin
                        st.session_state.is_logged_in = True
                        st.rerun()
                    else: st.sidebar.error(msg)
    st.title("💸 書展敗家計算機")
    st.info("👈 請先從左側登入，開始您的敗家之旅！")
    st.stop()

# 登入後顯示
st.sidebar.success(f"Hi, {st.session_state.user_id}")
st.session_state.budget = st.sidebar.number_input("💰 設定總預算", value=st.session_state.budget, step=100)
if st.sidebar.button("登出"):
    st.session_state.is_logged_in = False
    st.rerun()

# --- 主程式 ---
spreadsheet = connect_to_spreadsheet()
if not spreadsheet: st.error("連線失敗"); st.stop()
user_sheet, _ = get_user_sheet_with_auth(spreadsheet, st.session_state.user_id, st.session_state.user_pin)

st.title(f"💸 {st.session_state.user_id} 的敗家清單")

# --- 讀取並計算數據 (使用新的安全讀取函式) ---
df = load_data_safe(user_sheet)

# 確保價格欄位是數字
df['價格'] = pd.to_numeric(df['價格'], errors='coerce').fillna(0)

# 計算統計數據
total_spent = df[df['狀態'].isin(['待購', '已購'])]['價格'].sum()
item_count = len(df[df['狀態'].isin(['待購', '已購'])])
remain = st.session_state.budget - total_spent

# --- 儀表板區 ---
col_m1, col_m2, col_m3 = st.columns(3)
col_m1.metric("📚 書籍數量", f"{item_count} 本")
col_m2.metric("💸 預計花費", f"${int(total_spent)}")
col_m3.metric("💰 剩餘預算", f"${int(remain)}", delta_color="normal" if remain >= 0 else "inverse")

if remain < 0:
    st.error(f"⚠️ 警告：您已經超支 ${abs(int(remain))} 元了！")
else:
    st.progress(min(1.0, total_spent / st.session_state.budget) if st.session_state.budget > 0 else 0)

st.divider()

# --- A 區：掃描與新增 ---
with st.expander("🔍 **掃描/輸入 ISBN**", expanded=True):
    col1, col2 = st.columns([1, 2])
    with col1:
        with st.form("isbn_form", clear_on_submit=False): 
            isbn_input = st.text_input("ISBN 條碼")
            submitted = st.form_submit_button("🔍 查詢")

    if submitted and isbn_input:
        with st.spinner("☁️ 雲端搜尋..."):
            res = smart_book_search(isbn_input)
            st.session_state.search_result = res

    if st.session_state.get('search_result'):
        res = st.session_state.search_result
        if res['found']: st.success(f"✅ 找到：{res['書名']}")
        else: st.warning("⚠️ 需手動填寫")

        with st.form("confirm_form"):
            c1, c2 = st.columns([1, 2])
            with c1:
                if res['封面']: st.image(res['封面'], width=100)
                else: st.text("(無封面)")
                clean_isbn_val = clean_isbn_func(res['ISBN'])
                st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{clean_isbn_val}" target="_blank">🔍 查博客來</a>''', unsafe_allow_html=True)

            with c2:
                new_title = st.text_input("書名", value=res['書名'])
                new_author = st.text_input("作者", value=res['作者'])
                new_price = st.text_input("💰 價格", value=res['定價'])
                
                if st.form_submit_button("✅ 加入清單"):
                    new_row = [res['建檔時間'], new_title, new_author, res['ISBN'], new_price, "待購"]
                    user_sheet.append_row(new_row)
                    st.toast(f"已加入：{new_title}")
                    time.sleep(0.5)
                    st.session_state.search_result = None
                    st.rerun()

st.divider()

# --- B 區：清單管理 ---
tab1, tab2 = st.tabs(["📋 表格模式 (編輯)", "🖼️ 封面牆模式 (分享)"])

with tab1:
    edited_df = st.data_editor(
        df, 
        use_container_width=True, 
        num_rows="dynamic", 
        key="data_editor",
        column_config={
            "價格": st.column_config.NumberColumn("價格", format="$%d"),
            "狀態": st.column_config.SelectboxColumn("狀態", options=["待購", "已購", "猶豫中", "放棄"])
        }
    )
    if st.button("💾 儲存變更", type="primary"):
        with st.spinner("儲存中..."):
            if save_dataframe_to_sheet(user_sheet, edited_df, st.session_state.user_pin):
                st.success("儲存成功！")
                time.sleep(1)
                st.rerun()

with tab2:
    if not df.empty:
        cols = st.columns(4)
        for index, row in df.iterrows():
            with cols[index % 4]:
                if row['ISBN']:
                    img_url = search_google_books(str(row['ISBN']))['封面']
                    if img_url: st.image(img_url, use_container_width=True)
                    else: st.markdown("📚")
                
                st.caption(f"**{row['書名']}**")
                st.caption(f"${row['價格']} | {row['狀態']}")
                st.markdown("---")
    else:
        st.info("清單是空的，無法顯示封面牆。")