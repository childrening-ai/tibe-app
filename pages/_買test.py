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
st.set_page_config(page_title="買書小幫手", page_icon="📚", layout="wide")

# ==========================================
# 🎨 UI 美化工程 (暖陽珊瑚風格 - 手機並排終極版)
# ==========================================
st.markdown("""
    <style>
        /* --- 1. 全域設定 --- */
        .stApp { background-color: #FFFFFF; color: #4A4A4A; }
        .block-container { padding-top: 3.5rem !important; padding-bottom: 5rem !important; }
        [data-testid="stElementToolbar"] { display: none !important; }
        footer { visibility: hidden; }
        
        /* --- 2. 側邊欄設計 (維持原樣) --- */
        [data-testid="stSidebar"] {
            background-color: #FFF9F0;
            border-right: 2px solid #F3E5D8;
        }
        [data-testid="stSidebarCollapsedControl"] {
            background-color: #FF8C69 !important;
            border-radius: 50% !important;
            fill: white !important;
        }

        /* --- 3. 按鈕設計 (維持原樣) --- */
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
        }

        /* ============================================================
           🔥 4. 手機版面強制優化 (保留圓角風格，但強制擠在同一行)
           ============================================================ */

        /* 強制 Column 並排，禁止堆疊 */
        div[data-testid="column"] {
            display: inline-block !important; /* 強制行內顯示 */
            width: auto !important;
            flex: 1 !important;
            min-width: 0px !important; /* 允許縮到極小 */
            vertical-align: top !important; /* 對齊頂部 */
            padding: 0 2px !important; /* 減少左右間距 */
        }

        /* 輸入框樣式：找回原本的圓角與橘色框，但縮小內距以適應手機 */
        div[data-testid="stTextInput"] input, 
        div[data-testid="stNumberInput"] input {
            border-radius: 8px !important; /* 圓角 */
            border: 1px solid #FFCCBC !important; /* 淺橘框 */
            background-color: #FFFCF8 !important; /* 極淡橘底 */
            padding: 0px 5px !important; /* 縮小內距 */
            font-size: 0.95rem !important;
            height: auto !important;
            min-height: 35px !important;
        }
        
        /* 輸入框聚焦時 */
        div[data-testid="stTextInput"] input:focus, 
        div[data-testid="stNumberInput"] input:focus {
            border-color: #FF8C69 !important;
            box-shadow: 0 0 0 1px rgba(255, 140, 105, 0.2) !important;
        }

        /* 隱藏 Number Input 加減按鈕 (節省空間) */
        div[data-testid="stNumberInput"] button { display: none; }
        div[data-testid="stNumberInput"] input { text-align: center; }

        /* 極致壓縮垂直間距 */
        div[data-testid="stVerticalBlock"] > div {
            gap: 0.3rem !important;
        }
        
        /* 標籤 (Label) 樣式 - 配合 Python 中的 HTML */
        .custom-label {
            font-size: 0.8rem;
            color: #E65100; /* 深橘色文字 */
            font-weight: bold;
            margin-bottom: 2px;
            display: block;
        }

        /* 卡片容器樣式 */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border: 1px solid #FFE0B2 !important; /* 橘色邊框 */
            background-color: #fff;
            border-radius: 12px !important;
            padding: 12px !important;
            margin-bottom: 12px;
        }
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
if "is_guest" not in st.session_state: st.session_state.is_guest = False

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
                    return False, "⚠️ 密碼錯誤，或是此帳號已被他人使用！"
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

# --- 儲存功能 (修正 list index out of range 防呆版) ---
def save_user_cart_to_cloud(user_id, user_pin, current_df):
    client = get_gspread_client()
    if not client: return False
    try:
        sh = client.open(SHEET_NAME)
        ws = sh.worksheet(WORKSHEET_MASTER_CART)
        
        TARGET_COLS = ["User_ID", "Password", "書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
        
        # 讀取現有資料
        existing_data = ws.get_all_values()
        
        # 建立乾淨的 DataFrame (預設為空)
        df_clean = pd.DataFrame(columns=TARGET_COLS)
        
        # 🔥 關鍵修正：多重檢查，防止 index out of range
        has_data = False
        if existing_data and len(existing_data) > 0:
            # 確保第一列真的有資料，而不是空 list []
            if len(existing_data[0]) > 0:
                # 檢查第一格是否為 User_ID (標題列)
                if str(existing_data[0][0]).strip() == "User_ID":
                    has_data = True

        if has_data and len(existing_data) > 1:
            # 有標題且有內容，才轉換為 DataFrame
            # 使用 try-except 包裹 DataFrame 轉換，避免欄位數不符報錯
            try:
                df_clean = pd.DataFrame(existing_data[1:], columns=TARGET_COLS)
            except ValueError:
                # 如果欄位對不上 (例如 Sheet 有 8 欄，程式要 9 欄)，就強制只取前幾欄或重置
                # 這裡選擇簡單策略：若格式亂掉，視為舊資料不可用，只保留標題重寫
                pass

        # 1. 準備要寫入的新資料
        new_records = current_df.copy()
        new_records["User_ID"] = str(user_id)
        new_records["Password"] = str(user_pin)
        
        # 補齊欄位
        for col in TARGET_COLS:
            if col not in new_records.columns: new_records[col] = ""
        new_records = new_records[TARGET_COLS]

        # 2. 保留「其他人」的資料
        if not df_clean.empty:
            df_keep = df_clean[df_clean["User_ID"].astype(str) != str(user_id)]
        else:
            df_keep = pd.DataFrame(columns=TARGET_COLS)

        # 3. 合併
        df_final = pd.concat([df_keep, new_records], ignore_index=True)
        df_final = df_final.fillna("") # 再次確保沒有 NaN
        
        # 4. 寫回
        final_values = [TARGET_COLS] + df_final.values.tolist()
        ws.clear()
        ws.update(range_name='A1', values=final_values)
        return True
    except Exception as e:
        st.error(f"儲存失敗: {str(e)}") # 印出更詳細的錯誤
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

# --- 加入購物車 Callback (按鈕下方訊息版) ---
def submit_book_callback():
    val_title = st.session_state.get("in_title", "").strip()
    val_pub = st.session_state.get("in_pub", "").strip()
    val_price = st.session_state.get("in_price", 0.0)
    val_discount = st.session_state.get("in_discount", 100)
    val_note = st.session_state.get("in_note", "").strip()
    
    # 清除舊的訊息
    if "add_msg" in st.session_state: del st.session_state["add_msg"]

    # 計算折扣價
    try:
        p = float(val_price)
        calc_final = int(p * (val_discount / 100))
    except:
        p = 0
        calc_final = 0

    if not val_title:
        st.session_state.add_msg = {"type": "error", "text": "❌ 請至少輸入書名"}
        return

    new_row = pd.DataFrame([{
        "書名": val_title,
        "出版社": val_pub,
        "定價": p,
        "折數": val_discount,
        "折扣價": calc_final,
        "狀態": "待購", 
        "備註": val_note
    }])

    # 更新 Session
    if st.session_state.cart_data.empty:
        st.session_state.cart_data = new_row
    else:
        st.session_state.cart_data = pd.concat([st.session_state.cart_data, new_row], ignore_index=True)
    
    # 存檔與設定回饋訊息
    if not st.session_state.get("is_guest", False):
        save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, st.session_state.cart_data)
        # 🔥 修改：將成功訊息存入 session_state
        st.session_state.add_msg = {"type": "success", "text": f"✅ 已加入願望書單：{val_title}"}
    else:
        st.session_state.add_msg = {"type": "success", "text": f"👻 (訪客) 已暫存：{val_title}"}
    
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
    st.title("📚 買書小幫手")
    intro_col, login_col = st.columns([0.6, 0.4])
    with intro_col:
        st.markdown("""
        ### 歡迎使用！
        **功能**
        * AI拍照自動填寫書籍資料
        * 建立帳號可隨時儲存與修改書單
        * 支援匯出文字或表格檔案
        """)
    with login_col:
        with st.container(border=True):
            st.subheader("🔐 用戶登入")
            with st.form("login_form"):
                input_id = st.text_input("👤 帳號", placeholder="限輸入英文或數字")
                input_pin = st.text_input("🔑 密碼", type="password", placeholder="限輸入英文或數字")
                st.caption("※ 若帳號是第一次使用，系統將自動以此密碼註冊。")
                submit = st.form_submit_button("🚀 登入 / 註冊", use_container_width=True)
            
            # 🔥 新增：訪客按鈕
            if st.button("👀 免登入試用", use_container_width=True):
                st.session_state.is_guest = True
                st.session_state.user_id = "Guest"
                st.session_state.cart_data = pd.DataFrame() # 訪客從空清單開始
                st.session_state.is_logged_in = True
                st.rerun()

            if submit:
                if input_id and input_pin:
                    with st.spinner("驗證中..."):
                        is_valid, msg = check_login(input_id, input_pin)
                        
                        if is_valid:
                            # 登入成功，讀取資料
                            st.session_state.user_id = input_id
                            st.session_state.user_pin = input_pin
                            st.session_state.cart_data = load_user_cart(input_id)
                            
                            # 🔥 關鍵修正：登入成功後，強制關閉訪客模式
                            st.session_state.is_guest = False 
                            
                            st.session_state.is_logged_in = True
                            st.rerun()
                        else:
                            st.error(msg)
                else:
                    st.error("請輸入帳號與密碼")
    st.stop()

# ==========================================
# 主程式
# ==========================================
st.sidebar.success(f"Hi, {st.session_state.user_id}")
# (這裡移除了預算設定輸入框)
st.sidebar.markdown("---")
if st.sidebar.button("🚪 登出 / 結束試用", use_container_width=True):
    st.session_state.is_logged_in = False
    st.session_state.user_id = "" 
    st.session_state.cart_data = pd.DataFrame()
    st.rerun()

st.title(f"📷 新增書籍資料")
st.caption("請先輸入書籍資料，之後可在願望書單修改與刪除，最後請記得儲存到雲端再離開網頁")

# 確保 cart_data 是最新的 DataFrame
df = st.session_state.cart_data
expected_cols = ["書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
for c in expected_cols:
    if c not in df.columns: df[c] = "" 

# 轉換數值
df['定價'] = pd.to_numeric(df['定價'], errors='coerce').fillna(0)
df['折扣價'] = pd.to_numeric(df['折扣價'], errors='coerce').fillna(0)
if "折數" not in df.columns:
    if "折扣" in df.columns:
        df["折數"] = (pd.to_numeric(df["折扣"], errors='coerce').fillna(1.0) * 100).astype(int)
    else:
        df["折數"] = 100

# 計算金額 (供下方統計使用)
calc_price = df['折扣價'].where(df['折扣價'] > 0, df['定價'])
total_spent = calc_price[df['狀態'].isin(['待購', '已購'])].sum()
# (這裡移除了剩餘預算的計算)

# --- 1. 新增書籍 ---
with st.expander("➕ 新增書籍 (點擊展開/收合)", expanded=False):
    
    # AI 控制開關 (保持不變)
    if has_ai:
        if st.toggle("📸 開啟 AI 辨識", value=False):
            st.info("💡 提示：手機拍攝書籍封面、版權頁、或電腦螢幕上的博客來網頁。")
            uploaded_file = st.file_uploader("📂 點此開啟相機或圖庫", type=['jpg', 'png', 'jpeg'])
            
            if uploaded_file:
                st.image(uploaded_file, caption="預覽圖片", width=200)
                if st.button("✨ 開始 AI 辨識", type="primary"):
                    with st.spinner("AI 分析中..."):
                        image = Image.open(uploaded_file)
                        result = analyze_image_robust(image)
                        if result:
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
                            st.error("⚠️ 辨識失敗")
            st.markdown("---")

    # 手動輸入表單
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

    c3, c4, c5, c6 = st.columns([1.2, 1, 1, 1.2]) 
    with c3: new_publisher = st.text_input("🏢 出版社", key="in_pub")
    with c4: new_price = st.number_input("💰 定價", min_value=0, step=10, key="in_price")
    with c5: new_discount = st.number_input("📉 折數", min_value=1, max_value=100, value=79, step=1, key="in_discount")
    with c6: 
        calc_final = int(new_price * (new_discount / 100))
        st.write("") 
        st.markdown(
            f"""
            <div style="background-color: #FFF3E0; border: 2px solid #FF8C69; border-radius: 10px; text-align: center; padding: 2px 0;">
                <span style="font-size: 0.8rem; color: #E65100;">折後</span>
                <span style="font-size: 1.2rem; font-weight: bold; color: #BF360C;">${calc_final}</span>
            </div>
            """, unsafe_allow_html=True
        )
        
    c7, c8 = st.columns([3, 1])
    with c7: new_note = st.text_input("📝 備註 (選填)", key="in_note")
    with c8:
        st.write("")
        st.button("加入願望書單", type="primary", use_container_width=True, on_click=submit_book_callback)

    # 🔥 新增：在按鈕正下方顯示回饋訊息
    if "add_msg" in st.session_state and st.session_state.add_msg:
        msg = st.session_state.add_msg
        if msg["type"] == "error":
            st.error(msg["text"])
        else:
            st.success(msg["text"])

st.markdown("---")

# --- 2. 管理清單 (手機優化：卡片式版面) ---
st.subheader("📋 願望書單")

if df.empty:
    st.info("目前書單是空的，快點開上面「新增書籍」加入第一本書吧！")
else:
    # 統計資訊列
    st.markdown(
        f"""
        <div style="
            display: flex; 
            justify-content: space-around; 
            align-items: center;
            background-color: #FFF9F0; 
            padding: 12px 15px; 
            border-radius: 12px; 
            border: 1px solid #FFE0B2;
            margin-bottom: 25px; 
            font-size: 1rem;
            color: #5C4B45;
        ">
            <span>📚 <b>{len(df)}</b> 本</span>
            <span>💸 <b style="color: #D32F2F;">${int(total_spent)}</b></span>
        </div>
        """, 
        unsafe_allow_html=True
    )

    # 用於收集更新後的資料
    updated_rows = []
    indices_to_delete = []

    # 🔥 核心修改：模擬表格排版 (Table-Like Layout)
    for i, row in df.iterrows():
        with st.container(border=True):
            
            # --- Row 1: 狀態列 ---
            # 左邊是刪除，右邊是已購 (置右)
            c1_1, c1_2 = st.columns([0.3, 0.7]) 
            with c1_1:
                is_del = st.checkbox("刪除", key=f"del_{i}")
                if is_del: indices_to_delete.append(i)
            with c1_2:
                # 使用 HTML 讓 Checkbox 往右靠，增加視覺層次
                st.markdown('<div style="text-align: right;">', unsafe_allow_html=True)
                is_bought = st.checkbox("✅ 已購", value=(row["狀態"] == "已購"), key=f"status_{i}")
                st.markdown('</div>', unsafe_allow_html=True)
                new_status = "已購" if is_bought else "待購"

            st.markdown("<hr style='margin: 5px 0; border: 0; border-top: 1px dashed #eee;'>", unsafe_allow_html=True)

            # --- Row 2: 書名與出版社 (強制並排) ---
            # 比例 2:1
            c2_1, c2_2 = st.columns([2, 1]) 
            with c2_1:
                st.markdown('<span class="custom-label">書名</span>', unsafe_allow_html=True)
                new_title = st.text_input("書名", value=str(row["書名"]), label_visibility="collapsed", key=f"title_{i}")
            with c2_2:
                st.markdown('<span class="custom-label">出版社</span>', unsafe_allow_html=True)
                new_pub = st.text_input("出版社", value=str(row["出版社"]), label_visibility="collapsed", key=f"pub_{i}")

            # --- Row 3: 價格數據區 (強制並排) ---
            # 比例 1:1:1.2
            c3_1, c3_2, c3_3 = st.columns([1, 1, 1.2])
            
            with c3_1:
                st.markdown('<span class="custom-label">原價</span>', unsafe_allow_html=True)
                new_price = st.number_input("原價", value=int(row["定價"]), min_value=0, step=1, label_visibility="collapsed", key=f"price_{i}")
            
            with c3_2:
                st.markdown('<span class="custom-label">折數</span>', unsafe_allow_html=True)
                new_discount = st.number_input("折數", value=int(row["折數"]), min_value=1, max_value=100, step=1, label_visibility="collapsed", key=f"disc_{i}")
            
            with c3_3:
                current_calc = int(new_price * (new_discount / 100))
                # 售價直接用顯示的，不用輸入框，視覺上區隔開來
                st.markdown(
                    f"""
                    <span class="custom-label" style="color:#d32f2f;">售價</span>
                    <div style="font-size: 1.1rem; font-weight: bold; color: #D32F2F; border-bottom: 1px solid #eee; padding-bottom: 2px;">
                        ${current_calc}
                    </div>
                    """, 
                    unsafe_allow_html=True
                )

            # --- Row 4: 備註 (獨立一行) ---
            st.markdown('<span class="custom-label">備註</span>', unsafe_allow_html=True)
            new_note = st.text_input("備註", value=str(row["備註"]), label_visibility="collapsed", key=f"note_{i}")

            # 收集資料
            if not is_del:
                updated_rows.append({
                    "書名": new_title,
                    "出版社": new_pub,
                    "定價": new_price,
                    "折數": new_discount,
                    "折扣價": current_calc,
                    "狀態": new_status,
                    "備註": new_note
                })

    # --- 底部按鈕區 ---
    st.write("")
    if st.session_state.is_guest:
         st.button("💾 儲存修改 (訪客無法使用)", disabled=True, use_container_width=True)
    else:
        # 使用 callback 機制處理存檔
        if st.button("💾 儲存到雲端", type="primary", use_container_width=True):
            with st.spinner("正在更新資料庫..."):
                # 1. 將收集到的 dict 轉回 DataFrame
                # 因為上面已經 filter 過了，這裡直接轉就是最終結果
                new_df = pd.DataFrame(updated_rows)
                
                # 2. 更新 Session State
                st.session_state.cart_data = new_df
                
                # 3. 寫入雲端
                if save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, new_df):
                    st.success("✅ 儲存成功！")
                    time.sleep(1)
                    st.rerun()

# --- 3. 匯出功能 ---
st.markdown("---")
st.subheader("📤 下載願望書單")

if not df.empty:
    exp_c1, exp_c2 = st.columns(2)
    with exp_c1:
        out_cols = ["書名", "出版社", "定價", "折數", "折扣價", "狀態", "備註"] 
        valid_cols = [c for c in df.columns if c in out_cols]
        csv_data = df[valid_cols].to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "下載表格 (.csv)", 
            data=csv_data, 
            file_name=f"book_list_{st.session_state.user_id}.csv", 
            mime="text/csv",
            use_container_width=True
        )

    with exp_c2:
        txt_content = f"📚 {st.session_state.user_id} 的採購清單\n"
        txt_content += f"總花費：${int(total_spent)}\n" # 只保留總花費
        txt_content += "="*30 + "\n"
        
        for idx, row in df.iterrows():
            status_icon = "✅" if row['狀態'] == '已購' else "⬜"
            price_info = f"${row['折扣價']} (原${row['定價']} / {row['折數']}折)"
            txt_content += f"{status_icon} {row['書名']}\n"
            txt_content += f"   - {row['出版社']} | {price_info}\n"
            if row['備註']:
                txt_content += f"   - 備註: {row['備註']}\n"
            txt_content += "-"*20 + "\n"
            
        st.download_button(
            "下載文字檔 (.txt)", 
            data=txt_content, 
            file_name=f"book_list_{st.session_state.user_id}.txt", 
            mime="text/plain",
            use_container_width=True
        )