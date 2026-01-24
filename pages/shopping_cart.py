import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime
import time
import re
import urllib3
# 🔥 新增：AI 相關套件
import google.generativeai as genai
from PIL import Image

# 1. 頁面設定
st.set_page_config(page_title="書展採購清單", page_icon="📚", layout="wide")

# 設定區
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 🔥 新增：初始化 Gemini AI ---
def configure_genai():
    try:
        api_key = st.secrets.get("gemini_api_key")
        if api_key:
            genai.configure(api_key=api_key)
            return True
        return False
    except:
        return False

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
        saved_pin = sheet.acell('Z1').value
        if saved_pin and str(saved_pin).strip() != str(pin_code).strip():
            return None, "🔒 密碼錯誤！無法進入。"
        return sheet, "Success"
    except gspread.WorksheetNotFound:
        try:
            sheet = spreadsheet.add_worksheet(title=safe_id, rows=1, cols=26)
            headers = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
            sheet.update(range_name='A1', values=[headers])
            sheet.update_acell('Z1', str(pin_code))
            return sheet, "Success"
        except Exception as e:
            return None, f"建立失敗: {e}"

# --- 4. 資料儲存 (全表覆寫模式) ---
def save_data_overwrite(sheet, df, pin_code):
    try:
        df = df.fillna("")
        data = [df.columns.values.tolist()] + df.values.tolist()
        sheet.clear()
        sheet.update(range_name='A1', values=data)
        sheet.update_acell('Z1', str(pin_code))
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 🔥 新增：AI 辨識函式 ---
def analyze_image(image):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        prompt = """
        請分析這張圖片（書本封面、海報或網頁截圖），提取以下資訊。
        請直接回傳 JSON 格式，不要有Markdown標記，欄位如下：
        {
            "書名": "書籍名稱",
            "出版社": "出版社名稱(若無則留空)",
            "定價": "純數字(若無則填0)"
        }
        """
        response = model.generate_content([prompt, image])
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        import json
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"AI 辨識失敗: {e}")
        return None

# --- 主程式介面 ---

# 初始化 Session State (用於 AI 自動填表)
if "form_title" not in st.session_state: st.session_state.form_title = ""
if "form_publisher" not in st.session_state: st.session_state.form_publisher = ""
if "form_price" not in st.session_state: st.session_state.form_price = 0

# [側邊欄] 登入系統
st.sidebar.title("🔐 用戶登入")
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "budget" not in st.session_state: st.session_state.budget = 3000

# 設定 Gemini
has_ai = configure_genai()

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
    st.info("👈 請先從左側登入")
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
expected_cols = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]

try:
    data = sheet.get_all_values()
    if len(data) > 1:
        raw_rows = data[1:]
        clean_rows = []
        for row in raw_rows:
            if len(row) < len(expected_cols):
                row = row + [""] * (len(expected_cols) - len(row))
            row = row[:len(expected_cols)]
            clean_rows.append(row)
        df = pd.DataFrame(clean_rows, columns=expected_cols)
    else:
        df = pd.DataFrame(columns=expected_cols)
except Exception as e:
    st.error(f"讀取錯誤 (已重置表格結構): {e}")
    df = pd.DataFrame(columns=expected_cols)

# 數值運算預處理
df['定價'] = pd.to_numeric(df['定價'], errors='coerce').fillna(0)
df['折扣價'] = pd.to_numeric(df['折扣價'], errors='coerce').fillna(0)

# 預算計算
calc_price = df['折扣價'].where(df['折扣價'] > 0, df['定價'])
total_spent = calc_price[df['狀態'].isin(['待購', '已購'])].sum()
remain = st.session_state.budget - total_spent

# --- 頂部儀表板 ---
col1, col2, col3 = st.columns(3)
col1.metric("📚 書籍數量", f"{len(df)} 本")
col2.metric("💸 預計花費", f"${int(total_spent)}")
col3.metric("💰 剩餘預算", f"${int(remain)}", delta_color="normal" if remain >= 0 else "inverse")

st.markdown("---")

# --- 區域 A: 新增書籍 ---
st.subheader("➕ 新增書籍")

with st.container(border=True):
    # 🔥 新增：AI 拍照區
    with st.expander("📸 懶人模式：拍照/上傳辨識 (點此展開)", expanded=False):
        if has_ai:
            cam_col, up_col = st.columns(2)
            with cam_col:
                img_file = st.camera_input("直接拍照")
            with up_col:
                uploaded_file = st.file_uploader("或上傳圖片 (截圖/照片)", type=['jpg', 'png', 'jpeg'])
            
            target_img = img_file if img_file else uploaded_file
            
            if target_img:
                if st.button("✨ 開始 AI 辨識"):
                    with st.spinner("AI 正在看這本書..."):
                        image = Image.open(target_img)
                        result = analyze_image(image)
                        if result:
                            # 填入 Session State
                            st.session_state.form_title = result.get("書名", "")
                            st.session_state.form_publisher = result.get("出版社", "")
                            try:
                                p_str = str(result.get("定價", "0")).replace("$", "").replace(",", "")
                                st.session_state.form_price = int(float(p_str))
                            except:
                                st.session_state.form_price = 0
                            
                            st.success("辨識成功！請往下滑檢查資料 👇")
                            time.sleep(1)
                            st.rerun()
        else:
            st.warning("⚠️ 未設定 Gemini API Key，請檢查 secrets.json")

    # 手動填寫區 (value 綁定 session_state)
    c1, c2 = st.columns([3, 1])
    with c1:
        new_title = st.text_input("📘 書名 (必填)", value=st.session_state.form_title, key="in_title")
    with c2:
        st.write("") 
        st.write("") 
        if new_title:
            st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{new_title}" target="_blank">
            <button style="width:100%; padding: 0.5rem; background-color: #f0f2f6; border: 1px solid #ccc; border-radius: 5px; cursor: pointer;">
            🔍 查博客來
            </button></a>''', unsafe_allow_html=True)
        else:
            st.caption("輸入書名後出現查價鈕")

    c3, c4, c5, c6 = st.columns(4)
    with c3: new_publisher = st.text_input("🏢 出版社", value=st.session_state.form_publisher, key="in_pub")
    with c4: new_price = st.number_input("💰 定價", min_value=0, step=10, value=st.session_state.form_price, key="in_price")
    with c5: new_discount = st.selectbox("📉 折扣", options=[1.0, 0.79, 0.85, 0.9, 0.75, 0.66], index=1, format_func=lambda x: f"{int(x*100)}折" if x < 1 else "不打折")
    with c6: 
        calc_final = int(new_price * new_discount)
        new_final_price = st.number_input("🏷️ 折扣後價格", value=calc_final, step=1)
        
    c7, c8 = st.columns([3, 1])
    with c7: new_note = st.text_input("📝 備註 (選填)", key="in_note")
    with c8:
        st.write("")
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
                
                df = pd.concat([df, new_row], ignore_index=True)
                
                if save_data_overwrite(sheet, df, st.session_state.user_pin):
                    st.toast(f"✅ 已加入：{new_title}")
                    # 清空暫存
                    st.session_state.form_title = ""
                    st.session_state.form_publisher = ""
                    st.session_state.form_price = 0
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("❌ 請至少輸入書名")

st.markdown("---")

# --- 區域 B: 清單管理 ---
st.subheader("📋 管理清單")

if df.empty:
    st.info("目前清單是空的，請在上方新增書籍。")
else:
    df_display = df.copy()
    df_display.insert(0, "🗑️ 刪除", False)

    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        num_rows="fixed",
        key="main_editor",
        column_config={
            "🗑️ 刪除": st.column_config.CheckboxColumn("刪除?", width="small"),
            "定價": st.column_config.NumberColumn("定價", format="$%d"),
            "折扣": st.column_config.NumberColumn("折扣", format="%.2f"),
            "折扣價": st.column_config.NumberColumn("折扣價", format="$%d"),
            "狀態": st.column_config.SelectboxColumn("狀態", options=["待購", "已購", "猶豫中", "放棄"], width="medium"),
            "備註": st.column_config.TextColumn("備註", width="large"),
        }
    )

    btn_col1, btn_col2 = st.columns([1, 1])
    
    with btn_col1:
        rows_to_delete = edited_df[edited_df["🗑️ 刪除"] == True]
        delete_count = len(rows_to_delete)
        if delete_count > 0:
            if st.button(f"🗑️ 刪除選取的 {delete_count} 本書", type="secondary", use_container_width=True):
                final_df = edited_df[edited_df["🗑️ 刪除"] == False].drop(columns=["🗑️ 刪除"])
                save_data_overwrite(sheet, final_df, st.session_state.user_pin)
                st.success("刪除成功！")
                time.sleep(1)
                st.rerun()
        else:
            st.button("🗑️ 刪除 (請先勾選)", disabled=True, use_container_width=True)

    with btn_col2:
        clean_edited = edited_df.drop(columns=["🗑️ 刪除"])
        if st.button("💾 儲存表格修改", type="primary", use_container_width=True):
            save_data_overwrite(sheet, clean_edited, st.session_state.user_pin)
            st.success("✅ 修改已同步！")
            time.sleep(1)
            st.rerun()

st.write("")
st.caption("💡 提示：點擊「📸 懶人模式」可使用 AI 拍照自動填寫。")