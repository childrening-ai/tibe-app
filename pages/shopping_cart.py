import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime
import time
import re
import urllib3

# 1. 頁面設定
st.set_page_config(page_title="書展採購清單", page_icon="📚", layout="wide")

# 設定區
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 2. 連線功能 (穩定版) ---
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

# --- 3. 分頁與權限管理 ---
def get_user_sheet_with_auth(spreadsheet, user_id, pin_code):
    safe_id = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fa5]', '', str(user_id))
    if not safe_id: return None, "ID 無效"
    
    try:
        sheet = spreadsheet.worksheet(safe_id)
        # 驗證密碼 (讀取 Z1)
        saved_pin = sheet.acell('Z1').value
        if saved_pin and str(saved_pin).strip() != str(pin_code).strip():
            return None, "🔒 密碼錯誤！無法進入。"
        return sheet, "Success"
    except gspread.WorksheetNotFound:
        try:
            # 建立新分頁：只給標題列 (避免空行干擾)
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=1, cols=26)
            # 寫入您指定的欄位
            headers = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
            sheet.update(range_name='A1', values=[headers])
            # 寫入密碼到 Z1
            sheet.update_acell('Z1', str(pin_code))
            return sheet, "Success"
        except Exception as e:
            return None, f"建立失敗: {e}"

# --- 4. 資料儲存 (全表覆寫模式) ---
def save_data_overwrite(sheet, df, pin_code):
    try:
        # 處理 NaN
        df = df.fillna("")
        
        # 準備資料：標題 + 內容
        data = [df.columns.values.tolist()] + df.values.tolist()
        
        # 1. 清空
        sheet.clear()
        # 2. 寫入資料 (A1 開始)
        sheet.update(range_name='A1', values=data)
        # 3. 補回密碼 (Z1)
        sheet.update_acell('Z1', str(pin_code))
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 主程式介面 ---

# [側邊欄] 登入系統
st.sidebar.title("🔐 用戶登入")
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "budget" not in st.session_state: st.session_state.budget = 3000

# 未登入介面
if not st.session_state.is_logged_in:
    with st.sidebar.form("login_form"):
        input_id = st.text_input("👤 暱稱", placeholder="例如: Kevin")
        input_pin = st.text_input("🔑 密碼 (PIN)", type="password", placeholder="例如: 0000")
        if st.form_submit_button("🚀 登入 / 註冊"):
            if input_id and input_pin:
                ss = connect_to_spreadsheet()
                if ss:
                    sheet, msg = get_user_sheet_with_auth(ss, input_id, input_pin)
                    if sheet:
                        st.session_state.user_id = input_id
                        st.session_state.user_pin = input_pin
                        st.session_state.is_logged_in = True
                        st.rerun()
                    else:
                        st.sidebar.error(msg)
    st.title("📚 2026 書展採購清單")
    st.info("👈 請先從左側登入 (若無帳號，輸入新暱稱與密碼即自動註冊)")
    st.stop()

# 已登入介面
st.sidebar.success(f"Hi, {st.session_state.user_id}")
st.session_state.budget = st.sidebar.number_input("💰 總預算設定", value=st.session_state.budget, step=500)
if st.sidebar.button("登出"):
    st.session_state.is_logged_in = False
    st.session_state.user_id = ""
    st.rerun()

# 建立連線
ss = connect_to_spreadsheet()
if not ss: st.error("連線失敗"); st.stop()
sheet, _ = get_user_sheet_with_auth(ss, st.session_state.user_id, st.session_state.user_pin)

st.title(f"🛒 {st.session_state.user_id} 的採購清單")

# --- 資料讀取與處理 ---
try:
    data = sheet.get_all_values()
    # 指定欄位順序
    expected_cols = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
    
    if len(data) > 0:
        # 有資料，轉 DataFrame
        df = pd.DataFrame(data[1:], columns=data[0])
        
        # 防呆：如果欄位不對 (例如舊資料)，強制校正
        if not all(col in df.columns for col in expected_cols):
             df = pd.DataFrame(columns=expected_cols)
    else:
        # 完全沒資料
        df = pd.DataFrame(columns=expected_cols)
except:
    df = pd.DataFrame(columns=expected_cols)

# 數值運算預處理
df['定價'] = pd.to_numeric(df['定價'], errors='coerce').fillna(0)
df['折扣價'] = pd.to_numeric(df['折扣價'], errors='coerce').fillna(0)

# 預算計算 (以折扣價為準，如果沒填折扣價就用定價)
# 這裡做一個邏輯：計算時優先用「折扣價」，如果為0則用「定價」
calc_price = df['折扣價'].where(df['折扣價'] > 0, df['定價'])
total_spent = calc_price[df['狀態'].isin(['待購', '已購'])].sum()
remain = st.session_state.budget - total_spent

# --- 頂部儀表板 ---
col1, col2, col3 = st.columns(3)
col1.metric("📚 書籍數量", f"{len(df)} 本")
col2.metric("💸 預計花費", f"${int(total_spent)}")
col3.metric("💰 剩餘預算", f"${int(remain)}", delta_color="normal" if remain >= 0 else "inverse")

st.markdown("---")

# --- 區域 A: 新增書籍 (獨立大區塊) ---
st.subheader("➕ 新增書籍")

with st.container(border=True):
    # 第一列：書名搜尋與自動帶入連結
    c1, c2 = st.columns([3, 1])
    with c1:
        new_title = st.text_input("📘 書名 (必填)", key="in_title")
    with c2:
        st.write("") # 排版用
        st.write("") 
        if new_title:
            # 直接提供博客來連結，讓使用者點開看價格
            st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{new_title}" target="_blank">
            <button style="width:100%; padding: 0.5rem; background-color: #f0f2f6; border: 1px solid #ccc; border-radius: 5px; cursor: pointer;">
            🔍 查博客來
            </button></a>''', unsafe_allow_html=True)
        else:
            st.caption("輸入書名後出現查價鈕")

    # 第二列：詳細資料
    c3, c4, c5, c6 = st.columns(4)
    with c3:
        new_publisher = st.text_input("🏢 出版社", key="in_pub")
    with c4:
        new_price = st.number_input("💰 定價", min_value=0, step=10, key="in_price")
    with c5:
        # 折扣選單：常見折數 + 手動
        new_discount = st.selectbox("📉 折扣", options=[1.0, 0.79, 0.85, 0.9, 0.75, 0.66], index=1, format_func=lambda x: f"{int(x*100)}折" if x < 1 else "不打折")
    with c6:
        # 自動計算折扣價 (給預設值，但允許修改)
        calc_final = int(new_price * new_discount)
        new_final_price = st.number_input("🏷️ 折扣後價格", value=calc_final, step=1)
        
    # 第三列：備註與大按鈕
    c7, c8 = st.columns([3, 1])
    with c7:
        new_note = st.text_input("📝 備註 (選填)", key="in_note")
    with c8:
        st.write("") # 排版
        # 🔥 超大新增按鈕
        if st.button("➕ 加入清單", type="primary", use_container_width=True):
            if new_title:
                new_row = pd.DataFrame([{
                    "書名": new_title,
                    "出版社": new_publisher,
                    "定價": new_price,
                    "折扣": new_discount,
                    "折扣價": new_final_price,
                    "狀態": "待購",
                    "備註": new_note
                }])
                # 使用 concat 增加一行
                df = pd.concat([df, new_row], ignore_index=True)
                # 寫回雲端
                if save_data_overwrite(sheet, df, st.session_state.user_pin):
                    st.toast(f"✅ 已加入：{new_title}")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("❌ 請至少輸入書名")

st.markdown("---")

# --- 區域 B: 清單管理 (編輯與刪除) ---
st.subheader("📋 管理清單")

if df.empty:
    st.info("目前清單是空的，請在上方新增書籍。")
else:
    # 1. 增加「刪除」勾選欄位
    df_display = df.copy()
    df_display.insert(0, "🗑️ 刪除", False) # 在最前面加一欄 Boolean

    # 2. 顯示編輯器
    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        num_rows="fixed", # 禁止在這裡新增，強制用上方大按鈕新增
        key="main_editor",
        column_config={
            "🗑️ 刪除": st.column_config.CheckboxColumn("刪除?", help="勾選後按下方紅色按鈕刪除", width="small"),
            "定價": st.column_config.NumberColumn("定價", format="$%d"),
            "折扣": st.column_config.NumberColumn("折扣", format="%.2f"),
            "折扣價": st.column_config.NumberColumn("折扣價", format="$%d"),
            "狀態": st.column_config.SelectboxColumn("狀態", options=["待購", "已購", "猶豫中", "放棄"], width="medium"),
            "備註": st.column_config.TextColumn("備註", width="large"),
        }
    )

    # 3. 雙按鈕操作區 (獨立大按鈕)
    btn_col1, btn_col2 = st.columns([1, 1])
    
    # 刪除邏輯
    with btn_col1:
        # 計算勾選了幾個
        rows_to_delete = edited_df[edited_df["🗑️ 刪除"] == True]
        delete_count = len(rows_to_delete)
        
        if delete_count > 0:
            if st.button(f"🗑️ 刪除選取的 {delete_count} 本書", type="secondary", use_container_width=True):
                # 過濾掉被勾選的列
                final_df = edited_df[edited_df["🗑️ 刪除"] == False].drop(columns=["🗑️ 刪除"])
                save_data_overwrite(sheet, final_df, st.session_state.user_pin)
                st.success("刪除成功！")
                time.sleep(1)
                st.rerun()
        else:
            st.button("🗑️ 刪除 (請先勾選)", disabled=True, use_container_width=True)

    # 儲存邏輯
    with btn_col2:
        # 檢查是否有更動 (排除刪除欄位比較)
        clean_edited = edited_df.drop(columns=["🗑️ 刪除"])
        # 簡單比較 (略)
        
        if st.button("💾 儲存表格修改", type="primary", use_container_width=True):
            save_data_overwrite(sheet, clean_edited, st.session_state.user_pin)
            st.success("✅ 修改已同步！")
            time.sleep(1)
            st.rerun()

# 底部空間
st.write("")
st.caption("💡 提示：輸入書名後，點擊「查博客來」可快速看價格。下方表格可直接修改內容，記得按儲存。")