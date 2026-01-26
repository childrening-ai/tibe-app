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

        /* --- 🔥 12. 隱藏 DataEditor 內建功能列 (搜尋/放大) --- */
        [data-testid="stElementToolbar"] {
            display: none !important;
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

# --- 🔥 修正版：登入驗證函式 (新帳號會立刻寫入資料庫) ---
def check_login(user_id, input_pin):
    client = get_gspread_client()
    if not client: return False, "連線失敗"
    
    try:
        spreadsheet = client.open(SHEET_NAME)
        
        # 1. 嘗試取得分頁
        try:
            ws = spreadsheet.worksheet(WORKSHEET_MASTER_CART)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=WORKSHEET_MASTER_CART, rows=1000, cols=20)
        
        # 2. 標題檢查與補全
        existing_data = ws.get_all_values()
        HEADERS = ["User_ID", "Password", "書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
        
        if not existing_data:
            ws.update(range_name='A1', values=[HEADERS])
            existing_data = [HEADERS]
        
        # 3. 驗證帳號
        df = pd.DataFrame(existing_data[1:], columns=existing_data[0])
        
        # 確保有 User_ID 欄位
        if "User_ID" not in df.columns:
            return False, "資料庫格式錯誤 (缺 User_ID)"

        user_rows = df[df["User_ID"] == str(user_id)]
            
        if not user_rows.empty:
            # --- 舊帳號：檢查密碼 ---
            stored_pin = str(user_rows.iloc[0]["Password"]).strip()
            if stored_pin == "" or stored_pin == str(input_pin).strip():
                return True, "登入成功"
            else:
                return False, "⚠️ 密碼錯誤，或是此帳號已被他人使用！"
        else:
            # --- 🔥 修正關鍵：新帳號 -> 立刻佔位寫入 ---
            # 準備一列資料：[帳號, 密碼, 空白, 空白...]
            new_row = [str(user_id), str(input_pin)] + [""] * (len(HEADERS) - 2)
            ws.append_row(new_row)
            return True, "新帳號註冊成功"
        
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
            
            # 🔥 關鍵修正：過濾掉「書名」為空的資料 (即過濾掉註冊時的佔位資料)
            # 只有當「書名」有內容時，才算是一本真正的書
            if "書名" in user_df.columns:
                user_df = user_df[user_df["書名"].astype(str).str.strip() != ""]
            
            return user_df[cols_to_keep]
        return pd.DataFrame()
    except:
        return pd.DataFrame()

# --- 儲存功能 (修正版：雙重重置 Index 防止報錯) ---
def save_user_cart_to_cloud(user_id, user_pin, current_df):
    client = get_gspread_client()
    if not client: return False
    try:
        sh = client.open(SHEET_NAME)
        ws = sh.worksheet(WORKSHEET_MASTER_CART)
        
        # 1. 強制重置傳入資料的索引 (您原本加的)
        current_df = current_df.reset_index(drop=True)
        
        TARGET_COLS = ["User_ID", "Password", "書名", "出版社", "定價", "折扣", "折扣價", "狀態", "備註"]
        
        existing_data = ws.get_all_values()
        
        df_clean = pd.DataFrame(columns=TARGET_COLS)
        has_data = False
        if existing_data and len(existing_data) > 0:
            if len(existing_data[0]) > 0:
                if str(existing_data[0][0]).strip() == "User_ID":
                    has_data = True

        if has_data and len(existing_data) > 1:
            try:
                df_clean = pd.DataFrame(existing_data[1:], columns=TARGET_COLS)
            except ValueError:
                pass
        
        # 🔥🔥🔥 請確認這一行是「靠左」的 (不要縮在 try 裡面) 🔥🔥🔥
        # 這行會強制把所有可能造成報錯的重複索引都洗掉
        df_clean = df_clean.reset_index(drop=True)

        # 準備要寫入的新資料
        new_records = current_df.copy()

        if "折數" in new_records.columns:
            new_records.rename(columns={"折數": "折扣"}, inplace=True)

        new_records["User_ID"] = str(user_id)
        new_records["Password"] = str(user_pin)
        
        for col in TARGET_COLS:
            if col not in new_records.columns: new_records[col] = ""
        new_records = new_records[TARGET_COLS]

        # 保留「其他人」的資料
        if not df_clean.empty and "User_ID" in df_clean.columns:
            # 🔥🔥🔥 終極修正：加上 .values 🔥🔥🔥
            # 這會把篩選條件變成單純的 True/False 清單，強制 Pandas 忽略索引問題
            mask = df_clean["User_ID"].astype(str) != str(user_id)
            df_keep = df_clean[mask.values] 
        else:
            df_keep = pd.DataFrame(columns=TARGET_COLS)

        # 合併
        df_final = pd.concat([df_keep, new_records], ignore_index=True)
        df_final = df_final.fillna("") 
        
        # 寫回
        final_values = [TARGET_COLS] + df_final.values.tolist()
        ws.clear()
        ws.update(range_name='A1', values=final_values)
        return True
    except Exception as e:
        st.error(f"儲存失敗: {str(e)}")
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

has_ai = configure_genai()

# ==========================================
# 登入頁面 (垂直排列版)
# ==========================================
if not st.session_state.is_logged_in:
    st.title("📚 買書小幫手")
    
    # 1. 上方：歡迎文字 (直接寫，不用包在 column 裡)
    st.markdown("""
        ### 歡迎使用！
        **功能**
        * AI拍照自動填寫書籍資料
        * 建立帳號可隨時儲存與修改書單
        * 支援匯出文字或表格檔案
        """)
    
    # 2. 下方：登入卡片 (直接接在下面)
    with st.container(border=True):
        st.subheader("🔐 用戶登入")
        
        # --- 表單區塊 ---
        with st.form("login_form"):
            input_id = st.text_input("👤 帳號", placeholder="限輸入英文或數字")
            input_pin = st.text_input("🔑 密碼", type="password", placeholder="限輸入英文或數字")
            st.caption("※ 若帳號是第一次使用，系統將自動以此密碼註冊。")
            submit = st.form_submit_button("🚀 登入 / 註冊", use_container_width=True)
        
        # --- 訪客按鈕 (記得放在 form 外面) ---
        st.write("") # 加一點間距讓排版不擁擠
        if st.button("👀 免登入試用", use_container_width=True):
            st.session_state.is_guest = True
            st.session_state.user_id = "Guest"
            st.session_state.cart_data = pd.DataFrame() # 訪客從空清單開始
            st.session_state.is_logged_in = True
            st.rerun()

        # --- 登入驗證邏輯 ---
        if submit:
            if input_id and input_pin:
                with st.spinner("驗證中..."):
                    is_valid, msg = check_login(input_id, input_pin)
                    
                    if is_valid:
                        # 登入成功，讀取資料
                        st.session_state.user_id = input_id
                        st.session_state.user_pin = input_pin
                        st.session_state.cart_data = load_user_cart(input_id)
                        
                        # 登入成功後，強制關閉訪客模式
                        st.session_state.is_guest = False 
                        
                        st.session_state.is_logged_in = True
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                st.error("請輸入帳號與密碼")
    st.stop()

# ==========================================
# 🔥 安全性修補：跨頁面資料庫同步機制 (含資料讀取)
# ==========================================
if st.session_state.is_logged_in and not st.session_state.get("synced_shopping", False):
    # 1. 執行登入驗證 (確保帳號存在)
    check_login(st.session_state.user_id, st.session_state.user_pin)
    
    # 2. 🔥🔥🔥 關鍵補強：驗證後立刻「讀取舊資料」！ 🔥🔥🔥
    # 如果這裡沒讀取，程式會以為你是空的，一存檔就會把舊資料洗掉
    st.session_state.cart_data = load_user_cart(st.session_state.user_id)
    
    # 3. 標記已同步
    st.session_state.synced_shopping = True


# ==========================================
# 主程式
# ==========================================
st.sidebar.success(f"Hi, {st.session_state.user_id}")
# (這裡移除了預算設定輸入框)
st.sidebar.markdown("---")
if st.sidebar.button("🚪 登出 / 結束試用", use_container_width=True):
    # 1. 清除核心登入狀態
    st.session_state.is_logged_in = False
    st.session_state.user_id = ""
    st.session_state.cart_data = pd.DataFrame()
    
    # 2. 清除同步標記
    if "synced_shopping" in st.session_state:
        del st.session_state.synced_shopping
    if "synced_calendar" in st.session_state:
        del st.session_state.synced_calendar
        
    # 3. 🔥🔥🔥 關鍵修正：徹底清除殘留的輸入框與訊息 🔥🔥🔥
    # 這些 key 對應到 text_input 的 key 和回饋訊息
    keys_to_clear = ["add_msg", "in_title", "in_pub", "in_price", "in_discount", "in_note", "debug_ai_raw"]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
        
    # 4. 重新整理
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
        if st.toggle("開啟 AI 辨識", value=False):
            st.info("提示：手機拍攝書籍封面、版權頁、或電腦螢幕上的博客來網頁。")
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
        new_title = st.text_input("書名 (必填)", key="in_title")
    with c_form2:
        st.write("") 
        st.write("") 
        current_title = st.session_state.get("in_title", "")
        if current_title:
            st.markdown(f'''<a href="https://search.books.com.tw/search/query/key/{current_title}" target="_blank">
            <button style="width:100%; padding: 0.5rem; background-color: #FFF9F0; color: #E65100; border: 1px solid #FFCCBC; border-radius: 12px; cursor: pointer;">
            前往博客來搜尋
            </button></a>''', unsafe_allow_html=True)

    c3, c4, c5, c6 = st.columns([1.2, 1, 1, 1.2]) 
    with c3: new_publisher = st.text_input("出版社", key="in_pub")
    with c4: new_price = st.number_input("定價", min_value=0, step=10, key="in_price")
    with c5: new_discount = st.number_input("折數（100=不打折, 66=66折）", min_value=1, max_value=100, value=79, step=1, key="in_discount")
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
    with c7: new_note = st.text_input("備註 (選填)", key="in_note")
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

# --- 2. 管理清單 (無預算版) ---
st.subheader("📋 願望書單")
st.caption("欄位資料都可以再修改，售價在儲存後才會更新正確價格，離開網頁前請記得儲存喔！")

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

    df_display = df.copy()
    
    # 1. 資料轉換：建立「已購」勾選欄位 (將文字轉為 True/False)
    df_display["已購"] = df_display["狀態"] == "已購"
    
    # 2. 插入刪除欄位
    df_display.insert(0, "刪除", False)
    
    # 3. 🔥 關鍵修改：強制定義欄位顯示順序 (已購放在刪除與書名中間)
    cols_to_show = ["刪除", "已購", "書名", "出版社", "定價", "折數", "折扣價", "備註"]
    
    # 表格設定
    edited_df = st.data_editor(
        df_display[cols_to_show], # 只傳入指定順序的欄位
        use_container_width=True,
        num_rows="fixed",
        hide_index=True, 
        key="main_editor",
        column_config={
            "刪除": st.column_config.CheckboxColumn("刪", width="small"),
            # 🔥 修改：改為 Checkbox，標題設為 "已購"
            "已購": st.column_config.CheckboxColumn("已購", width="small"), 
            "書名": st.column_config.TextColumn("書名", width="medium"),
            "出版社": st.column_config.TextColumn("出版社", width="small"),
            "定價": st.column_config.NumberColumn("定價", format="$%d", width="small"),
            "折數": st.column_config.NumberColumn("折數", min_value=1, max_value=100, step=1, format="%d", width="small"),
            "折扣價": st.column_config.NumberColumn("售價", format="$%d", width="small", disabled=True),
            # "狀態" 欄位已不再顯示，改用 "已購"
            "備註": st.column_config.TextColumn("備註", width="small"),
        }
    )
    
    # 底部按鈕區
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        rows_to_delete = edited_df[edited_df["刪除"] == True]
        if len(rows_to_delete) > 0:
            if st.button(f"🗑️ 刪除 ({len(rows_to_delete)})", type="secondary", use_container_width=True):
                # 這裡要小心，edited_df 現在是用我們自定義的欄位順序
                # 先取出沒被刪除的資料
                kept_data = edited_df[edited_df["刪除"] == False].copy()
                
                # 4. 存檔前轉換：把「已購 (True/False)」轉回「狀態 (已購/待購)」
                kept_data["狀態"] = kept_data["已購"].apply(lambda x: "已購" if x else "待購")
                
                # 移除暫時的欄位，還原成資料庫格式
                final_df = kept_data.drop(columns=["刪除", "已購"])
                
                # 重算價格
                final_df["折扣價"] = (final_df["定價"] * (final_df["折數"] / 100)).astype(int)
                
                st.session_state.cart_data = final_df
                if not st.session_state.is_guest:
                    save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, final_df)
                st.toast("已刪除！")
                st.rerun()
                
    with btn_col2:
        if st.session_state.is_guest:
             st.button("💾 儲存 (訪客無法使用)", disabled=True, use_container_width=True)
        else:
            if st.button("💾 儲存到雲端", type="primary", use_container_width=True):
                with st.spinner("正在同步..."):
                    # 取得編輯後的資料
                    current_edit = edited_df.copy()
                    
                    # 4. 存檔前轉換：把「已購 (True/False)」轉回「狀態 (已購/待購)」
                    current_edit["狀態"] = current_edit["已購"].apply(lambda x: "已購" if x else "待購")
                    
                    # 移除暫時的欄位
                    final_df = current_edit.drop(columns=["刪除", "已購"])
                    
                    # 強制重算價格
                    final_df["折扣價"] = (final_df["定價"] * (final_df["折數"] / 100)).astype(int)
                    
                    st.session_state.cart_data = final_df
                    if save_user_cart_to_cloud(st.session_state.user_id, st.session_state.user_pin, final_df):
                        st.success("✅ 儲存成功！")
                        time.sleep(1)
                        st.rerun()

# --- 3. 匯出功能 ---
st.markdown("---")
st.subheader("📤 下載願望書單")
st.caption("表格csv檔可以用 excel 或 google 表單開啟")

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