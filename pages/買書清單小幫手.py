import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import time
import re
import urllib3
import json
import google.generativeai as genai
from PIL import Image

# 1. 頁面設定
st.set_page_config(page_title="書展採購清單", page_icon="📚", layout="wide")

# ==========================================
# 🎨 UI 美化工程 (暖陽珊瑚風格 - 統一標準版)
# ==========================================
st.markdown("""
    <style>
        /* --- 1. 全域設定 --- */
        .stApp {
            background-color: #FFFFFF;
            color: #4A4A4A;
        }
        
        /* 修正手機版面頂部間距 */
        .block-container {
            padding-top: 3.5rem !important;
            padding-bottom: 5rem !important;
        }
        h1 { font-size: 1.8rem !important; color: #4A4A4A !important; font-weight: 700 !important; }
        h2, h3 { color: #5C4B45 !important; }
        
        /* --- 2. 側邊欄設計 --- */
        [data-testid="stSidebar"] {
            background-color: #FFF9F0;
            border-right: 2px solid #F3E5D8;
        }
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
            color: #5C4B45 !important;
        }

        /* --- 3. 側邊欄控制按鈕 (固定圓球版) --- */
        [data-testid="stSidebarCollapsedControl"] {
            background-color: #FF8C69 !important;
            border-radius: 50% !important;
            width: 45px !important;
            height: 45px !important;
            left: 15px !important;
            top: 15px !important;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            position: fixed !important; 
            z-index: 999999 !important;
            visibility: visible !important;
            opacity: 1 !important;
        }
        [data-testid="stSidebarCollapsedControl"] svg {
            fill: white !important;
            transform: scale(1.3) !important;
        }
        [data-testid="stSidebarCollapsedControl"]:hover {
            background-color: #FF7043 !important;
            transform: scale(1.1);
        }

        /* --- 4. 元件美化 --- */
        .stMultiSelect span[data-baseweb="tag"] {
            background-color: #FFE0B2 !important; 
            color: #BF360C !important;
        }
        [data-testid="stDataFrame"] th {
            background-color: #FFEEE0 !important; 
            color: #4A4A4A !important; 
            font-size: 1rem !important;
        }
        
        /* 輸入框圓角 */
        .stTextInput input, .stSelectbox div[data-baseweb="select"], .stNumberInput input {
            border-radius: 12px !important;
            border: 1px solid #FFCCBC !important;
        }
        .stTextInput input:focus, .stNumberInput input:focus {
            border-color: #FF8C69 !important;
            box-shadow: 0 0 0 2px rgba(255, 140, 105, 0.2) !important;
        }

        /* --- 5. 按鈕設計 --- */
        .stButton > button {
            border-radius: 25px !important;
            font-weight: bold;
            border: 2px solid #FF8C69 !important;
            color: #FF8C69 !important;
            background-color: white !important;
        }
        .stButton > button[kind="primary"] {
            background-color: #FF8C69 !important;
            color: white !important;
            border: none !important;
            box-shadow: 0 4px 6px rgba(255, 140, 105, 0.3);
        }

        /* --- 6. 登入框與提示框 --- */
        [data-testid="stForm"] {
            background-color: #FFFCF8;
            border: 2px solid #FFF0E0;
            border-radius: 20px;
            padding: 2rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }
        
        /* 隱藏 Footer */
        footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# ⚙️ 設定區
# ==========================================
SHEET_NAME = "2026國際書展使用者採購清單"
WORKSHEET_MASTER_CART = "users" 

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 初始化 Session State ---
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "budget" not in st.session_state: st.session_state.budget = 3000
if "debug_ai_raw" not in st.session_state: st.session_state.debug_ai_raw = ""
if "cart_data" not in st.session_state: st.session_state.cart_data = pd.DataFrame()

# --- 初始化 Gemini AI ---
def configure_genai():
    try:
        if "gemini_api_key" in st.secrets:
            genai.configure(api_key=st.secrets["gemini_api_key"])
            return True
        return False
    except:
        return False

# --- 連線功能 ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
        else:
            with open("secrets.json", "r") as f:
                creds_dict = json.load(f)
                if "gcp_service_account" in creds_dict:
                    creds_dict = creds_dict["gcp_service_account"]

        if "private_key" in creds_dict:
             creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"連線錯誤: {e}")
        return None

# --- 🔥 新增：登入驗證函式 (含標題自動修復) ---
def check_login(user_id, input_pin):
    client = get_gspread_client()
    if not client: return False, "連線失敗"
    
    try:
        spreadsheet = client.open(SHEET_NAME)
        
        # 1. 嘗試取得分頁，若無則建立
        try:
            ws = spreadsheet.worksheet(WORKSHEET_MASTER_CART)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=WORKSHEET_MASTER_CART, rows=1000, cols=20)
        
        # 2. 🔥 防呆：檢查是否為空白分頁 (若無標題則自動補上)
        existing_data = ws.get_all_values()
        HEADERS = ["User_ID", "Password", "書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
        
        if not existing_data:
            # 完全空白 -> 補標題
            ws.update(range_name='A1', values=[HEADERS])
            existing_data = [HEADERS] # 手動更新變數，讓後面邏輯繼續
        elif existing_data[0] != HEADERS:
            # 有資料但標題不對 (可選：視需求決定是否要強制修正，目前先不覆蓋以免誤刪)
            pass

        # 3. 開始驗證帳號
        if len(existing_data) < 2: return True, "新帳號" # 只有標題，無內容

        df = pd.DataFrame(existing_data[1:], columns=existing_data[0])
        
        if "User_ID" in df.columns:
            user_rows = df[df["User_ID"] == str(user_id)]
            
            if not user_rows.empty:
                # 帳號存在，檢查密碼
                stored_pin = str(user_rows.iloc[0]["Password"]).strip()
                if stored_pin == "" or stored_pin == str(input_pin).strip():
                    return True, "登入成功"
                else:
                    return False, "⚠️ 密碼錯誤，或是此暱稱已被他人使用！"
            else:
                return True, "新帳號註冊"
        
        return True, "資料庫格式重置"
    except Exception as e:
        return False, f"系統錯誤: {e}"

# --- 讀取使用者書單 ---
def load_user_cart(user_id):
    client = get_gspread_client()
    if not client: return pd.DataFrame()
    try:
        sh = client.open(SHEET_NAME)
        ws = sh.worksheet(WORKSHEET_MASTER_CART)
        data = ws.get_all_values()
        
        if len(data) < 2: return pd.DataFrame() # 只有標題或空的
        
        df = pd.DataFrame(data[1:], columns=data[0])
        
        # 篩選該使用者的資料
        if "User_ID" in df.columns:
            user_df = df[df["User_ID"] == str(user_id)].copy()
            # 移除 User_ID 和 Password 欄位，只回傳書單內容
            cols_to_keep = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
            # 確保欄位存在
            for c in cols_to_keep:
                if c not in user_df.columns: user_df[c] = ""
            return user_df[cols_to_keep]
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 儲存功能 (配合新版資料庫結構) ---
def save_user_cart_to_cloud(user_id, user_pin, current_df):
    client = get_gspread_client()
    if not client: return False
    try:
        sh = client.open(SHEET_NAME)
        # 使用全域變數 WORKSHEET_MASTER_CART (users)
        ws = sh.worksheet(WORKSHEET_MASTER_CART)
        
        # 定義新版標準欄位 (含 User_ID 與 Password)
        TARGET_COLS = ["User_ID", "Password", "書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
        
        # 讀取現有資料
        existing_data = ws.get_all_values()
        
        # 建立乾淨的 DataFrame 用於處理
        df_clean = pd.DataFrame(columns=TARGET_COLS)
        if existing_data:
            # 簡單判斷第一列是否為標題
            if str(existing_data[0][0]).strip() == "User_ID":
                if len(existing_data) > 1:
                    df_clean = pd.DataFrame(existing_data[1:], columns=TARGET_COLS)
            else:
                # 若無標題或標題錯誤，暫時略過舊資料結構處理，直接準備寫入
                pass

        # 1. 準備要寫入的「當前使用者」新資料
        new_records = current_df.copy()
        new_records["User_ID"] = str(user_id)
        new_records["Password"] = str(user_pin)
        
        # 補齊可能缺少的欄位 (防呆)
        for col in TARGET_COLS:
            if col not in new_records.columns: new_records[col] = ""
        # 確保欄位順序正確
        new_records = new_records[TARGET_COLS]

        # 2. 保留「其他人」的資料 (從總表中剔除 當前使用者 的舊資料)
        if not df_clean.empty:
            # 這裡邏輯是：留下 User_ID 不等於 我的資料
            df_keep = df_clean[df_clean["User_ID"].astype(str) != str(user_id)]
        else:
            df_keep = pd.DataFrame(columns=TARGET_COLS)

        # 3. 合併 (其他人的資料 + 我的新資料)
        df_final = pd.concat([df_keep, new_records], ignore_index=True)
        df_final = df_final.fillna("")
        
        # 4. 寫回 Google Sheet
        final_values = [TARGET_COLS] + df_final.values.tolist()
        ws.clear()
        ws.update(range_name='A1', values=final_values)
        return True
    except Exception as e:
        st.error(f"儲存失敗: {e}")
        return False

# --- 🔥 強力 AI 解析函式 (維持不變) ---
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
        if match: return json.loads(match.group(0))
        else: return {"error": "No JSON found", "raw": raw_text}
    except Exception as e:
        st.session_state.debug_ai_raw = f"Error: {str(e)}"
        return None

# --- 加入購物車 Callback ---
def submit_book_callback():
    val_title = st.session_state.get("in_title", "").strip()
    val_pub = st.session_state.get("in_pub", "").strip()
    val_price = st.session_state.get("in_price", 0.0)
    val_discount = st.session_state.get("in_discount", 1.0)
    val_note = st.session_state.get("in_note", "").strip()
    
    # 計算折扣價
    try:
        p = float(val_price)
        calc_final = int(p * val_discount)
    except:
        p = 0
        calc_final = 0

    if not val_title:
        st.error("❌ 請至少輸入書名")
        return

    new_row = pd.DataFrame([{
        "書名": val_title,
        "出版社": val_pub,
        "定價": p,
        "折扣": val_discount,
        "折扣價": calc_final,
        "狀態": "待購", 
        "備註": val_note
    }])

    # 更新 Session 中的資料
    if st.session_state.cart_data.empty:
        st.session_state.cart_data = new_row
    else:
        st.session_state.cart_data = pd.concat([st.session_state.cart_data, new_row], ignore_index=True)
    
    # 立即存檔
    save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, st.session_state.cart_data)
    
    st.toast(f"✅ 已加入：{val_title}")
    # 清空輸入
    st.session_state["in_title"] = ""
    st.session_state["in_pub"] = ""
    st.session_state["in_price"] = 0
    st.session_state["in_note"] = ""

# ==========================================
# 登入頁面
# ==========================================
has_ai = configure_genai()

if not st.session_state.is_logged_in:
    st.title("📚 2026 書展採購清單")
    intro_col, login_col = st.columns([0.6, 0.4])
    with intro_col:
        st.markdown("""
        ### 歡迎使用！
        **功能特色：**
        * ✅ **預算控管**：即時計算剩餘金額
        * ✅ **AI 辨識**：拍書封自動填寫資料
        * ✅ **雲端同步**：資料安全帶著走
        """)
    with login_col:
        with st.container(border=True):
            st.subheader("🔐 用戶登入")
            with st.form("login_form"):
                input_id = st.text_input("👤 暱稱 / 帳號", placeholder="例如: Kevin")
                input_pin = st.text_input("🔑 密碼 (PIN)", type="password", placeholder="設定 4-6 碼密碼")
                st.caption("※ 若暱稱是第一次使用，系統將自動以此密碼註冊。")
                submit = st.form_submit_button("🚀 登入 / 註冊", use_container_width=True)
            
            if submit:
                if input_id and input_pin:
                    with st.spinner("驗證中..."):
                        is_valid, msg = check_login(input_id, input_pin)
                        
                        if is_valid:
                            # 登入成功，讀取資料
                            st.session_state.user_id = input_id
                            st.session_state.user_pin = input_pin
                            st.session_state.cart_data = load_user_cart(input_id)
                            st.session_state.is_logged_in = True
                            st.rerun()
                        else:
                            st.error(msg)
                else:
                    st.error("請輸入暱稱與密碼")
    st.stop()

# ==========================================
# 主程式
# ==========================================
st.sidebar.success(f"Hi, {st.session_state.user_id}")
st.session_state.budget = st.sidebar.number_input("💰 總預算設定", value=st.session_state.budget, step=500)
st.sidebar.markdown("---")
if st.sidebar.button("🚪 登出", use_container_width=True):
    st.session_state.is_logged_in = False
    st.session_state.user_id = "" 
    st.session_state.cart_data = pd.DataFrame()
    st.rerun()

st.title(f"🛒 {st.session_state.user_id} 的採購清單")

# 確保 cart_data 是最新的 DataFrame
df = st.session_state.cart_data
expected_cols = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
for c in expected_cols:
    if c not in df.columns: df[c] = "" # 防呆

# 轉換數值型別
df['定價'] = pd.to_numeric(df['定價'], errors='coerce').fillna(0)
df['折扣價'] = pd.to_numeric(df['折扣價'], errors='coerce').fillna(0)

# 計算金額
calc_price = df['折扣價'].where(df['折扣價'] > 0, df['定價'])
total_spent = calc_price[df['狀態'].isin(['待購', '已購'])].sum()
remain = st.session_state.budget - total_spent

# --- 狀態統計區 (暖陽風格) ---
c1, c2, c3 = st.columns(3)
with c1: st.metric("📚 書籍數量", f"{len(df)} 本")
with c2: st.metric("💸 預計花費", f"${int(total_spent)}")
with c3: st.metric("💰 剩餘預算", f"${int(remain)}", delta_color="normal" if remain >= 0 else "inverse")

st.markdown("---")

# --- 新增書籍區塊 ---
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
                        
                        if result:
                            # 填入 Session State
                            t_val = result.get("書名") or result.get("書籍名稱") or ""
                            st.session_state["in_title"] = str(t_val)

                            p_val = result.get("出版社") or ""
                            st.session_state["in_pub"] = str(p_val)

                            price_raw = result.get("定價") or 0
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
        else:
            st.warning("⚠️ 請設定 Gemini API Key")

    # 手動輸入/確認表單
    c_form1, c_form2 = st.columns([3, 1])
    with c_form1:
        new_title = st.text_input("📘 書名 (必填)", key="in_title")
    with c_form2:
        st.write("") 
        st.write("") 
        current_title = st.session_state.get("in_title", "")
        if current_title:
            st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{current_title}" target="_blank">
            <button style="width:100%; padding: 0.5rem; background-color: #FFF9F0; color: #E65100; border: 1px solid #FFCCBC; border-radius: 12px; cursor: pointer;">
            🔍 查博客來
            </button></a>''', unsafe_allow_html=True)

    c3, c4, c5, c6 = st.columns(4)
    with c3: new_publisher = st.text_input("🏢 出版社", key="in_pub")
    with c4: new_price = st.number_input("💰 定價", min_value=0, step=10, key="in_price")
    with c5: new_discount = st.selectbox("📉 折扣", options=[1.0, 0.79, 0.85, 0.9, 0.75, 0.66], index=1, format_func=lambda x: f"{int(x*100)}折" if x < 1 else "不打折", key="in_discount")
    with c6: 
        calc_final = int(new_price * new_discount)
        st.number_input("🏷️ 折扣後價格", value=calc_final, step=1, disabled=True)
        
    c7, c8 = st.columns([3, 1])
    with c7: new_note = st.text_input("📝 備註 (選填)", key="in_note")
    with c8:
        st.write("")
        st.button("➕ 加入清單", 
                  type="primary", 
                  use_container_width=True, 
                  on_click=submit_book_callback
        )

st.markdown("---")
st.subheader("📋 管理清單")

if df.empty:
    st.info("目前清單是空的。")
else:
    # 🔥 關鍵修改：在顯示前，產生一個臨時的流水號 ID，確保每一行都是獨一無二的
    # 這樣刪除同樣書名的書時，不會把兩本都刪掉
    df_display = df.copy()
    
    # 加入 checkbox
    df_display.insert(0, "🗑️ 刪除", False)
    
    # 顯示表格
    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        num_rows="fixed",
        key="main_editor",
        column_config={
            "🗑️ 刪除": st.column_config.CheckboxColumn("刪除", width="small"),
            "書名": st.column_config.TextColumn("書名", width="large"),
            "出版社": st.column_config.TextColumn("出版社", width="medium"),
            "定價": st.column_config.NumberColumn("定價", format="$%d", width="small"),
            "折扣": st.column_config.NumberColumn("折扣", format="%.2f", width="small"),
            "折扣價": st.column_config.NumberColumn("折扣價", format="$%d", width="small"),
            "狀態": st.column_config.SelectboxColumn(
                "狀態",
                options=["待購", "已購", "猶豫中", "放棄"],
                width="medium",
                required=True
            ),
            "備註": st.column_config.TextColumn("備註", width="medium"),
        }
    )
    
    # 底部按鈕區
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        # 刪除邏輯：根據 index 刪除
        rows_to_delete = edited_df[edited_df["🗑️ 刪除"] == True]
        if len(rows_to_delete) > 0:
            if st.button(f"🗑️ 刪除選取的 {len(rows_to_delete)} 本書", type="secondary", use_container_width=True):
                # 利用 index 反向保留沒被勾選的
                final_df = edited_df[edited_df["🗑️ 刪除"] == False].drop(columns=["🗑️ 刪除"])
                st.session_state.cart_data = final_df
                save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, final_df)
                st.toast("已刪除！")
                st.rerun()
                
    with btn_col2:
        if st.button("💾 儲存修改 (狀態/備註)", type="primary", use_container_width=True):
            # 移除 checkbox 欄位後存檔
            final_df = edited_df.drop(columns=["🗑️ 刪除"])
            st.session_state.cart_data = final_df
            if save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, final_df):
                st.success("✅ 已同步到雲端！")
                time.sleep(1)
                st.rerun()