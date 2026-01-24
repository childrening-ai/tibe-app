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

# --- 🔥 強力 AI 解析函式 ---
def analyze_image_robust(image):
    try:
        model_name = 'gemini-2.0-flash'
        model = genai.GenerativeModel(model_name)

        prompt = """
        你是一個精通書籍資訊的 AI 助理。請分析這張圖片（書本封面、海報或網頁截圖）。
        請嚴格遵守以下 JSON 格式回傳，不要包含任何 Markdown 標記：
        {
            "書名": "書籍名稱",
            "出版社": "出版社名稱",
            "定價": 0
        }

        規則：
        1. 【書名】：找出畫面中最顯眼的標題。
        2. 【出版社】：找出出版商名稱 (若找不到可留空)。
        3. 【定價】：
           - 尋找「定價」或「價格」關鍵字後的數字。
           - ⚠️ 重要：忽略刪除線，忽略紅色的優惠價，我要原價。
           - 只回傳純數字 (Integer)。
        """
        
        generation_config = genai.types.GenerationConfig(temperature=0.0)
        response = model.generate_content([prompt, image], generation_config=generation_config)
        raw_text = response.text
        
        st.session_state.debug_ai_raw = raw_text

        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            json_str = match.group(0)
            return json.loads(json_str)
        else:
            return {"error": "No JSON found", "raw": raw_text}

    except Exception as e:
        st.session_state.debug_ai_raw = f"Error: {str(e)}"
        return None

# --- Callback 函式 ---
def submit_book_callback(sheet, current_df, pin_code):
    val_title = st.session_state.get("in_title", "").strip()
    val_pub = st.session_state.get("in_pub", "").strip()
    val_price = st.session_state.get("in_price", 0)
    val_discount = st.session_state.get("in_discount", 1.0)
    val_note = st.session_state.get("in_note", "").strip()
    calc_final = int(val_price * val_discount)

    if not val_title:
        st.error("❌ 請至少輸入書名")
        return

    new_row = pd.DataFrame([{
        "書名": val_title,
        "出版社": val_pub,
        "定價": val_price,
        "折扣": val_discount,
        "折扣價": calc_final,
        "狀態": "待購", # 預設狀態
        "備註": val_note
    }])

    updated_df = pd.concat([current_df, new_row], ignore_index=True)
    if save_data_overwrite(sheet, updated_df, pin_code):
        st.toast(f"✅ 已加入：{val_title}")
        st.session_state["in_title"] = ""
        st.session_state["in_pub"] = ""
        st.session_state["in_price"] = 0
        st.session_state["in_note"] = ""

# --- 主程式 ---

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
            
            uploaded_file = st.file_uploader("📂 點此開啟相機或圖庫 (推薦)", type=['jpg', 'png', 'jpeg'])
            
            if uploaded_file:
                st.image(uploaded_file, caption="預覽圖片", width=200)
                if st.button("✨ 開始 AI 辨識 (Gemini 2.0)", type="primary"):
                    with st.spinner("AI 分析中..."):
                        image = Image.open(uploaded_file)
                        result = analyze_image_robust(image)
                        
                        if result:
                            t_val = result.get("書名") or result.get("書籍名稱") or result.get("Title") or ""
                            st.session_state["in_title"] = str(t_val)

                            p_val = result.get("出版社") or result.get("Publisher") or ""
                            st.session_state["in_pub"] = str(p_val)

                            price_raw = result.get("定價") or result.get("Price") or 0
                            try:
                                if isinstance(price_raw, str):
                                    clean_p = re.sub(r'[^\d]', '', price_raw)
                                    final_p = int(float(clean_p)) if clean_p else 0
                                else:
                                    final_p = int(price_raw)
                            except:
                                final_p = 0
                            
                            st.session_state["in_price"] = final_p
                            
                            st.success(f"✅ 辨識成功！")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("⚠️ 辨識失敗，無法解析資料。")
            
            if st.session_state.debug_ai_raw:
                with st.expander("🕵️‍♂️ Debug 視窗", expanded=False):
                    st.code(st.session_state.debug_ai_raw)
        else:
            st.warning("⚠️ 請設定 Gemini API Key")

    # 表單區
    c1, c2 = st.columns([3, 1])
    with c1:
        new_title = st.text_input("📘 書名 (必填)", key="in_title")
    with c2:
        st.write("") 
        st.write("") 
        current_title = st.session_state.get("in_title", "")
        if current_title:
            st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{current_title}" target="_blank">
            <button style="width:100%; padding: 0.5rem; background-color: #f0f2f6; border: 1px solid #ccc; border-radius: 5px; cursor: pointer;">
            🔍 查博客來
            </button></a>''', unsafe_allow_html=True)

    c3, c4, c5, c6 = st.columns(4)
    with c3: new_publisher = st.text_input("🏢 出版社", key="in_pub")
    with c4: new_price = st.number_input("💰 定價", min_value=0, step=10, key="in_price")
    
    with c5: new_discount = st.selectbox("📉 折扣", options=[1.0, 0.79, 0.85, 0.9, 0.75, 0.66], index=1, format_func=lambda x: f"{int(x*100)}折" if x < 1 else "不打折", key="in_discount")
    
    with c6: 
        calc_final = int(new_price * new_discount)
        new_final_price = st.number_input("🏷️ 折扣後價格", value=calc_final, step=1)
        
    c7, c8 = st.columns([3, 1])
    with c7: new_note = st.text_input("📝 備註 (選填)", key="in_note")
    with c8:
        st.write("")
        st.button("➕ 加入清單", 
                  type="primary", 
                  use_container_width=True, 
                  on_click=submit_book_callback,
                  args=(sheet, df, st.session_state.user_pin)
        )

st.markdown("---")
st.subheader("📋 管理清單")

if df.empty:
    st.info("目前清單是空的。")
else:
    df_display = df.copy()
    df_display.insert(0, "🗑️ 刪除", False)
    
    # 🔥 關鍵修改：設定 column_config 使狀態變成下拉選單
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
            # 👇 這裡強制設定為下拉選單
            "狀態": st.column_config.SelectboxColumn(
                "狀態",
                options=["待購", "已購", "猶豫中", "放棄"],
                width="medium",
                required=True # 設為必填，防止變成空白
            ),
            "備註": st.column_config.TextColumn("備註", width="large"),
        }
    )
    
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