import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime
import time
import re
import urllib3
import json
import google.generativeai as genai
from PIL import Image

# 1. 頁面設定
st.set_page_config(page_title="書展採購清單", page_icon="📚", layout="wide")

# 設定區
SHEET_NAME = "2026國際書展採購清單"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 初始化 Gemini AI ---
def configure_genai():
    try:
        api_key = st.secrets.get("gemini_api_key")
        if api_key:
            genai.configure(api_key=api_key)
            return True
        return False
    except:
        return False

# --- 連線功能 ---
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

# --- 分頁與權限 ---
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

# --- 儲存資料 ---
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

# --- 🔥 強力 AI 解析函式 (安全除錯版) ---
def analyze_image_robust(image):
    st.info("🔄 步驟 1: 進入 AI 分析函式...") # Debug 訊息
    
    # 1. 檢查圖片物件
    if image is None:
        st.error("❌ 錯誤：圖片物件是空的 (None)")
        return None
    
    st.text(f"📸 步驟 2: 圖片讀取成功，尺寸: {image.size}")

    # 2. 設定 AI 模型 (先用最穩的 1.5-flash，確認能跑再說)
    try:
        # 暫時改回 1.5-flash，因為 2.0-flash-exp 很容易報錯 404
        model = genai.GenerativeModel('gemini-2.0-flash')
        st.text("🤖 步驟 3: AI 模型 (1.5-flash) 初始化成功")
    except Exception as e:
        st.error(f"❌ 錯誤：模型初始化失敗。原因：{e}")
        return None

    # 3. 準備 Prompt
    prompt = """
    你是一個精通書籍資訊的 AI 助理。請分析這張圖片。
    請嚴格遵守以下 JSON 格式回傳，不要包含任何 Markdown 標記：
    {
        "書名": "書籍名稱",
        "出版社": "出版社名稱",
        "定價": 0
    }
    
    規則：
    1. 【定價】：請尋找「定價：」後面的數字。
    2. 忽略刪除線，禁止讀取紅色優惠價。
    3. 只回傳純數字 (Integer)。
    """

    # 4. 發送請求 (這是最容易崩潰的地方)
    try:
        st.text("📡 步驟 4: 正在發送圖片給 Google...")
        response = model.generate_content([prompt, image])
        st.text("✅ 步驟 5: 收到 Google 回傳資料")
        
        raw_text = response.text
        st.session_state.debug_ai_raw = raw_text # 存起來給你看

    except Exception as e:
        # 這裡會抓出具體的 API 錯誤 (例如 Key 無效、配額不足)
        st.error(f"❌ 錯誤：呼叫 API 失敗。原因：{e}")
        st.session_state.debug_ai_raw = f"API Error: {e}"
        return None

    # 5. 解析 JSON
    try:
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            json_str = match.group(0)
            data = json.loads(json_str)
            st.text("🎉 步驟 6: JSON 解析成功！")
            return data
        else:
            st.warning("⚠️ 警告：AI 有回傳文字，但找不到 JSON 格式。")
            return {"error": "No JSON", "raw": raw_text}
    except Exception as e:
        st.error(f"❌ 錯誤：JSON 解析失敗。原因：{e}")
        return None

# --- 主程式 ---

if "form_title" not in st.session_state: st.session_state.form_title = ""
if "form_publisher" not in st.session_state: st.session_state.form_publisher = ""
if "form_price" not in st.session_state: st.session_state.form_price = 0
if "debug_ai_raw" not in st.session_state: st.session_state.debug_ai_raw = ""

st.sidebar.title("🔐 用戶登入")
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "budget" not in st.session_state: st.session_state.budget = 3000

has_ai = configure_genai()

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
                    else: st.sidebar.error(msg)
    st.title("📚 2026 書展採購清單")
    st.info("👈 請先從左側登入")
    st.stop()

st.sidebar.success(f"Hi, {st.session_state.user_id}")
st.session_state.budget = st.sidebar.number_input("💰 總預算設定", value=st.session_state.budget, step=500)
if st.sidebar.button("登出"):
    st.session_state.is_logged_in = False
    st.session_state.user_id = ""
    st.rerun()

ss = connect_to_spreadsheet()
if not ss: st.error("連線失敗"); st.stop()
sheet, _ = get_user_sheet_with_auth(ss, st.session_state.user_id, st.session_state.user_pin)

st.title(f"🛒 {st.session_state.user_id} 的採購清單")

# 讀取資料
expected_cols = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
try:
    data = sheet.get_all_values()
    if len(data) > 1:
        raw_rows = data[1:]
        clean_rows = []
        for row in raw_rows:
            if len(row) < len(expected_cols): row = row + [""] * (len(expected_cols) - len(row))
            row = row[:len(expected_cols)]
            clean_rows.append(row)
        df = pd.DataFrame(clean_rows, columns=expected_cols)
    else:
        df = pd.DataFrame(columns=expected_cols)
except Exception as e:
    df = pd.DataFrame(columns=expected_cols)

df['定價'] = pd.to_numeric(df['定價'], errors='coerce').fillna(0)
df['折扣價'] = pd.to_numeric(df['折扣價'], errors='coerce').fillna(0)
calc_price = df['折扣價'].where(df['折扣價'] > 0, df['定價'])
total_spent = calc_price[df['狀態'].isin(['待購', '已購'])].sum()
remain = st.session_state.budget - total_spent

col1, col2, col3 = st.columns(3)
col1.metric("📚 書籍數量", f"{len(df)} 本")
col2.metric("💸 預計花費", f"${int(total_spent)}")
col3.metric("💰 剩餘預算", f"${int(remain)}", delta_color="normal" if remain >= 0 else "inverse")

st.markdown("---")
st.subheader("➕ 新增書籍")

with st.container(border=True):
    # AI 區塊
    with st.expander("📸 AI 智慧辨識 (點此展開)", expanded=True):
        if has_ai:
            st.info("💡 提示：手機拍攝書籍封面、或直接拍電腦螢幕上的博客來網頁皆可。")
            
            uploaded_file = st.file_uploader("📂 點此開啟相機或圖庫", type=['jpg', 'png', 'jpeg'])
            
            if uploaded_file:
                st.image(uploaded_file, caption="預覽圖片", width=200)
                if st.button("✨ 開始 AI 辨識", type="primary"):
                    with st.spinner("AI 分析中..."):
                        image = Image.open(uploaded_file)
                        result = analyze_image_robust(image)
                        
                        if result and "書名" in result:
                            st.session_state.form_title = result.get("書名", "")
                            st.session_state.form_publisher = result.get("出版社", "")
                            try:
                                p_val = result.get("定價", 0)
                                if isinstance(p_val, str):
                                    p_val = re.sub(r'[^\d]', '', p_val)
                                st.session_state.form_price = int(float(p_val)) if p_val else 0
                            except:
                                st.session_state.form_price = 0
                            
                            st.success("✅ 辨識完成！")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error("⚠️ 辨識失敗，請參考下方除錯資訊")
            
            if st.session_state.debug_ai_raw:
                with st.expander("🕵️‍♂️ Debug 視窗：AI 回傳原始內容", expanded=False):
                    st.code(st.session_state.debug_ai_raw)
        else:
            st.warning("⚠️ 請設定 Gemini API Key")

    # 表單區
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
                    st.session_state.form_title = ""
                    st.session_state.form_publisher = ""
                    st.session_state.form_price = 0
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("❌ 請至少輸入書名")

st.markdown("---")
st.subheader("📋 管理清單")

if df.empty:
    st.info("目前清單是空的。")
else:
    df_display = df.copy()
    df_display.insert(0, "🗑️ 刪除", False)
    edited_df = st.data_editor(df_display, use_container_width=True, num_rows="fixed", key="main_editor", column_config={"🗑️ 刪除": st.column_config.CheckboxColumn("刪除?", width="small")})
    
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        rows = edited_df[edited_df["🗑️ 刪除"] == True]
        if len(rows) > 0:
            if st.button(f"🗑️ 刪除選取的 {len(rows)} 本書", type="secondary"):
                final = edited_df[edited_df["🗑️ 刪除"] == False].drop(columns=["🗑️ 刪除"])
                save_data_overwrite(sheet, final, st.session_state.user_pin)
                st.success("刪除成功！"); st.rerun()
    with btn_col2:
        if st.button("💾 儲存修改", type="primary"):
            final = edited_df.drop(columns=["🗑️ 刪除"])
            save_data_overwrite(sheet, final, st.session_state.user_pin)
            st.success("✅ 已同步！"); st.rerun()