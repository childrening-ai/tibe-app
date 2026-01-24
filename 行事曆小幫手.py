import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import datetime
from datetime import timedelta
from streamlit_calendar import calendar
from ics import Calendar, Event
import time
import re
import json

# 1. 頁面基本設定
st.set_page_config(
    page_title="2026 書展排程神器",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==========================================
# 🎨 UI 美化工程 (親子柔和風格 - 修正深色區塊版)
# ==========================================
st.markdown("""
    <style>
        /* --- 1. 全域設定 (強制淺色主題感) --- */
        .stApp {
            background-color: #FFFFFF;
            color: #4A4A4A;
        }
        
        /* 修正手機版面頂部間距 (避開箭頭) */
        .block-container {
            padding-top: 3rem !important; /* 加大一點，讓箭頭更清楚 */
            padding-bottom: 5rem !important;
        }
        h1 { font-size: 1.8rem !important; color: #4A4A4A !important; font-weight: 700 !important; }
        h2, h3 { color: #5C4B45 !important; } /* 深咖啡色標題 */
        
        /* --- 2. 側邊欄設計 (奶油米色) --- */
        [data-testid="stSidebar"] {
            background-color: #FFF9F0;
            border-right: 2px solid #F3E5D8;
        }
        /* 側邊欄文字顏色 */
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {
            color: #5C4B45 !important;
        }

        /* --- 3. 側邊欄控制按鈕 (全時段固定顯示 + 強制不隱藏) --- */
        
        /* 針對收合(箭頭)與展開(叉叉)兩種狀態 */
        section[data-testid="stSidebar"] > div > div:nth-child(2), /* 針對某些版本的 sidebar header */
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stSidebarExpandedControl"] {
            
            /* 🔥 關鍵 1：強制顯示，不准淡出 */
            opacity: 1 !important;
            visibility: visible !important;
            display: flex !important;
            
            /* 外觀設計 (珊瑚粉圓球) */
            background-color: #FF8C69 !important; 
            color: white !important;
            border-radius: 50%;
            border: 2px solid #FFFFFF;
            box-shadow: 2px 2px 6px rgba(0,0,0,0.15);
            
            /* 大小設定 */
            width: 3rem !important;
            height: 3rem !important;
            
            /* 🔥 關鍵 2：強制固定位置 (釘在左上角) */
            position: fixed !important;
            top: 1rem !important;
            left: 1rem !important;
            
            /* 🔥 關鍵 3：層級最高，浮在所有內容之上 */
            z-index: 1000002 !important; 
            
            /* 內容置中 */
            align-items: center !important;
            justify-content: center !important;
            
            /* 移除 Streamlit 預設的 hover 變透明動畫 */
            transition: transform 0.2s !important; 
        }

        /* 滑鼠移過去的效果 (放大就好，不要閃爍) */
        [data-testid="stSidebarCollapsedControl"]:hover,
        [data-testid="stSidebarExpandedControl"]:hover {
            transform: scale(1.1);
            background-color: #FF7043 !important;
            opacity: 1 !important; /* 再次確保 hover 時也是不透明 */
        }
        
        /* 修正圖示線條粗細，讓它在粉色底上更清楚 */
        [data-testid="stSidebarExpandedControl"] svg,
        [data-testid="stSidebarCollapsedControl"] svg {
            width: 1.6rem !important;
            height: 1.6rem !important;
            stroke-width: 2.5px !important; 
        }

        /* --- 4. 修正深色元件 (針對您的截圖修正) --- */
        
        /* 下拉選單 (Multiselect) - 去除黑色背景 */
        .stMultiSelect span[data-baseweb="tag"] {
            background-color: #FFE0B2 !important; /* 淺橘色標籤 */
            color: #BF360C !important;
        }
        
        /* 表格 (Data Editor) - 修正黑色標題列 */
        [data-testid="stDataFrame"] th {
            background-color: #FFEEE0 !important; /* 淺橘粉底 */
            color: #4A4A4A !important; /* 深灰字 */
            font-size: 1rem !important;
        }
        [data-testid="stDataFrame"] td {
            background-color: #FFFFFF !important;
            color: #4A4A4A !important;
        }
        
        /* 輸入框 (Text Input) - 圓潤化 */
        .stTextInput input, .stSelectbox div[data-baseweb="select"] {
            border-radius: 12px !important;
            border: 1px solid #FFCCBC !important;
        }
        .stTextInput input:focus {
            border-color: #FF8C69 !important;
            box-shadow: 0 0 0 2px rgba(255, 140, 105, 0.2) !important;
        }

        /* --- 5. 按鈕設計 (糖果風格) --- */
        .stButton > button {
            border-radius: 25px !important;
            font-weight: bold;
            border: 2px solid #FF8C69 !important;
            color: #FF8C69 !important;
            background-color: white !important;
            transition: all 0.2s;
        }
        /* 主要按鈕 (如儲存) */
        .stButton > button[kind="primary"] {
            background-color: #FF8C69 !important;
            color: white !important;
            box-shadow: 0 4px 6px rgba(255, 140, 105, 0.3);
            border: none !important;
        }
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }

        /* --- 6. 分頁籤 (Tabs) - 膠囊風格 --- */
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
            background-color: transparent;
        }
        .stTabs [data-baseweb="tab"] {
            height: 40px;
            background-color: #F5F5F5;
            border-radius: 20px;
            color: #888;
            font-weight: 600;
            border: none;
            padding: 0 20px;
        }
        .stTabs [aria-selected="true"] {
            background-color: #FF8C69 !important;
            color: white !important;
            box-shadow: 0 2px 5px rgba(255, 140, 105, 0.4);
        }

        /* --- 7. 日曆 (FullCalendar) 配色 --- */
        .fc-toolbar-title {
            color: #4A4A4A !important;
            font-family: 'Helvetica', sans-serif;
        }
        .fc-col-header-cell {
            background-color: #FFF3E0 !important; /* 星期幾的背景 */
            color: #E65100 !important;
        }
        .fc-button-primary {
            background-color: #FF8C69 !important;
            border-color: #FF8C69 !important;
        }

        /* --- 8. 登入框與提示框 --- */
        [data-testid="stForm"] {
            background-color: #FFFCF8;
            border: 2px solid #FFF0E0;
            border-radius: 20px;
            padding: 2rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }
        .success-box {
            background-color: #E8F5E9; /* 柔和綠 */
            color: #2E7D32;
            border: 2px solid #C8E6C9;
            border-radius: 12px;
            padding: 1rem;
            text-align: center;
            font-weight: bold;
        }
        
        /* 隱藏不必要的元素 */
        footer {visibility: hidden;}
        #MainMenu {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# ==========================================
# ⚙️ 設定區
# ==========================================
SHEET_NAME_MASTER = "2026國際書展行事曆" 
WORKSHEETS_TO_LOAD = ["國際書展"]
SHEET_NAME_USERS_DB = "2026國際書展使用者行事曆"
WORKSHEET_USERS_TAB = "users" 

# --- 初始化 Session State ---
if "calendar_focus_date" not in st.session_state: st.session_state.calendar_focus_date = "2026-02-04" 
if "prev_selection_counts" not in st.session_state: st.session_state.prev_selection_counts = {}
if "user_id" not in st.session_state: st.session_state.user_id = ""
if "user_pin" not in st.session_state: st.session_state.user_pin = ""
if "is_logged_in" not in st.session_state: st.session_state.is_logged_in = False
if "is_guest" not in st.session_state: st.session_state.is_guest = False 
if "saved_ids" not in st.session_state: st.session_state.saved_ids = []
if "save_success_msg" not in st.session_state: st.session_state.save_success_msg = None # 用來控制成功訊息顯示

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
        print(f"連線錯誤: {e}")
        return None

# --- 資料讀取 ---
@st.cache_data(ttl=300)
def load_master_data():
    client = get_gspread_client()
    if not client: return None, "連線失敗"

    try:
        spreadsheet = client.open(SHEET_NAME_MASTER)
        all_frames = []
        STANDARD_COLS = ["日期", "時間", "活動名稱", "地點", "主講人", "主持人", "類型", "備註", "詳細內容"]

        for ws_name in WORKSHEETS_TO_LOAD:
            try:
                worksheet = spreadsheet.worksheet(ws_name)
                data = worksheet.get_all_values()
                if len(data) < 2: continue
                
                df = pd.DataFrame(data[1:], columns=data[0])
                df['來源'] = ws_name 
                df.columns = [c.strip() for c in df.columns]
                
                if "主講人" not in df.columns and "講者" in df.columns:
                    df.rename(columns={"講者": "主講人"}, inplace=True)

                for col in STANDARD_COLS:
                    if col not in df.columns: df[col] = "" 
                
                df = df.fillna("")
                df['id'] = df.apply(lambda x: f"{x['日期']}_{x['時間']}_{x['活動名稱']}", axis=1)
                all_frames.append(df)
            except Exception as e:
                print(f"讀取 {ws_name} 失敗: {e}")
                pass

        if not all_frames: return pd.DataFrame(), "無資料"
        final_df = pd.concat(all_frames, ignore_index=True)
        return final_df, "Success"
    except Exception as e:
        return None, str(e)

# --- 使用者資料讀取 ---
def load_user_saved_ids(user_id):
    client = get_gspread_client()
    if not client: return []
    try:
        sh = client.open(SHEET_NAME_USERS_DB)
        ws = sh.worksheet(WORKSHEET_USERS_TAB)
        data = ws.get_all_values()
        if len(data) < 2: return []
        df = pd.DataFrame(data[1:], columns=data[0])
        if "User_ID" in df.columns and "ID" in df.columns:
            user_data = df[df["User_ID"] == str(user_id)]
            return user_data["ID"].tolist()
        return []
    except Exception as e:
        print(f"讀取失敗: {e}")
        return []

# --- 儲存功能 (自動修復標題版) ---
def save_user_schedule_to_cloud(user_id, selected_df):
    client = get_gspread_client()
    if not client: return False, "連線失敗"
    try:
        sh = client.open(SHEET_NAME_USERS_DB)
        ws = sh.worksheet(WORKSHEET_USERS_TAB)
        TARGET_COLS = ["User_ID", "ID", "日期", "時間", "活動名稱", "地點"]
        existing_data = ws.get_all_values()
        
        df_clean = pd.DataFrame(columns=TARGET_COLS)
        if existing_data:
            if str(existing_data[0][0]).strip() == "User_ID":
                if len(existing_data) > 1:
                    df_clean = pd.DataFrame(existing_data[1:], columns=TARGET_COLS)
            else:
                valid_data = [row for row in existing_data if any(field.strip() for field in row)]
                if valid_data:
                    df_clean = pd.DataFrame(valid_data, columns=TARGET_COLS)

        new_records_df = pd.DataFrame()
        new_records_df["User_ID"] = [str(user_id)] * len(selected_df)
        col_mapping = {"id": "ID", "日期": "日期", "時間": "時間", "活動名稱": "活動名稱", "地點": "地點"}
        for src_col, target_col in col_mapping.items():
            if src_col in selected_df.columns:
                new_records_df[target_col] = selected_df[src_col].values
            else:
                new_records_df[target_col] = ""
        new_records_df = new_records_df[TARGET_COLS]

        if not df_clean.empty:
            df_keep = df_clean[df_clean["User_ID"].astype(str) != str(user_id)]
        else:
            df_keep = pd.DataFrame(columns=TARGET_COLS)

        df_final = pd.concat([df_keep, new_records_df], ignore_index=True)
        df_final = df_final.fillna("")
        
        final_values = [TARGET_COLS] + df_final.values.tolist()
        ws.clear()
        ws.update(range_name='A1', values=final_values)
        return True, "儲存成功"
    except gspread.WorksheetNotFound:
        return False, f"找不到分頁 '{WORKSHEET_USERS_TAB}'"
    except Exception as e:
        return False, f"儲存失敗: {str(e)}"

def parse_datetime_range(date_str, time_str):
    try:
        clean_date = str(date_str).split(" ")[0].strip()
        clean_time = str(time_str).replace("：", ":").replace("~", "-").replace(" ", "")
        if "-" in clean_time:
            parts = clean_time.split("-")
            start_t = parts[0]; end_t = parts[1]
        else:
            start_t = clean_time; end_t = clean_time 
        
        fmt = "%Y-%m-%d %H:%M"
        try:
            start_dt = datetime.datetime.strptime(f"{clean_date} {start_t}", fmt)
            end_dt = datetime.datetime.strptime(f"{clean_date} {end_t}", fmt)
        except:
             # 如果解析失敗嘗試秒數
            fmt_sec = "%Y-%m-%d %H:%M:%S"
            try:
                start_dt = datetime.datetime.strptime(f"{clean_date} {start_t}", fmt_sec)
                end_dt = datetime.datetime.strptime(f"{clean_date} {end_t}", fmt_sec)
            except:
                return None, None
        return start_dt, end_dt
    except:
        return None, None

# ==========================================
# 登入頁面
# ==========================================
if not st.session_state.is_logged_in:
    st.title("📅 2026 書展排程神器")
    intro_col, login_col = st.columns([0.6, 0.4])
    with intro_col:
        st.markdown("""
        ### 歡迎使用！
        這是專為書展設計的排程小幫手。
        **功能特色：**
        * ✅ **自動排程**：勾選活動，自動生成週曆
        * ✅ **雲端同步**：登入後可儲存您的專屬行程
        * ✅ **離線帶著走**：支援匯出手機行事曆 (.ics)
        """)
        st.info("💡 建議先以「訪客模式」試用！")
    with login_col:
        with st.container(border=True):
            st.subheader("🔐 用戶登入")
            with st.form("login_form"):
                input_id = st.text_input("👤 暱稱 / 帳號", placeholder="例如: Kevin")
                input_pin = st.text_input("🔑 密碼 (PIN)", type="password", placeholder="自訂 4-6 碼")
                
                submit = st.form_submit_button("🚀 登入 / 註冊", use_container_width=True)
            
            if st.button("👀 免登入試用", use_container_width=True):
                st.session_state.is_guest = True
                st.session_state.user_id = "Guest"
                st.session_state.is_logged_in = True
                st.rerun()

            if submit:
                if input_id and input_pin:
                    with st.spinner("正在讀取雲端行程..."):
                        saved_ids = load_user_saved_ids(input_id)
                        st.session_state.saved_ids = saved_ids
                        st.session_state.user_id = input_id
                        st.session_state.user_pin = input_pin
                        st.session_state.is_guest = False
                        st.session_state.is_logged_in = True
                    st.rerun()
                else:
                    st.error("請輸入暱稱與密碼")
    st.stop() 

# ==========================================
# 主程式
# ==========================================
with st.sidebar:
    if st.session_state.is_guest:
        st.warning("👀 訪客模式")
        st.caption("無法使用雲端儲存功能")
    else:
        st.success(f"👤 {st.session_state.user_id}")
    st.markdown("---")
    if st.button("🚪 登出 / 結束試用", use_container_width=True):
        st.session_state.is_logged_in = False
        st.session_state.is_guest = False
        st.session_state.user_id = ""
        st.session_state.saved_ids = []
        st.session_state.save_success_msg = None
        st.rerun()

raw_df, msg = load_master_data()
if raw_df is None or raw_df.empty:
    st.error(f"⚠️ 資料讀取失敗：{msg}")
    st.stop()

proc_df = raw_df.copy()
proc_df[['start_dt', 'end_dt']] = proc_df.apply(lambda x: pd.Series(parse_datetime_range(x['日期'], x['時間'])), axis=1)

all_selected_ids = []
current_selection_counts = {}

# 標題
st.title("📅 2026 書展排程神器")
if st.session_state.is_guest:
    st.caption("訪客模式：資料不會儲存")

# ==========================================
# 區塊 1：活動清單與勾選 (邏輯修正版)
# ==========================================
st.subheader("1. 勾選活動 ✅")

with st.expander("🔎 進階篩選", expanded=False):
    c1, c2, c3 = st.columns(3)
    with c1: f_loc = st.multiselect("地點", options=sorted(list(set(proc_df['地點'].astype(str)))))
    with c2: f_type = st.multiselect("類型", options=sorted(list(set(proc_df['類型'].astype(str)))))
    with c3: f_key = st.text_input("關鍵字")

mask = [True] * len(proc_df)
if f_loc: mask &= proc_df['地點'].isin(f_loc)
if f_type: mask &= proc_df['類型'].isin(f_type)
if f_key: 
    mask &= (proc_df['活動名稱'].str.contains(f_key, case=False) | proc_df['主講人'].str.contains(f_key, case=False))

filtered_df = proc_df[mask]
unique_dates = sorted(list(set(filtered_df['日期'].unique())))

if not unique_dates:
    st.info("沒有符合條件的活動")
else:
    tab_names = [d[5:] if len(str(d))>5 else str(d) for d in unique_dates]
    tabs = st.tabs(tab_names)
    
    for i, date_str in enumerate(unique_dates):
        with tabs[i]:
            # 準備該日期的資料
            day_df = filtered_df[filtered_df['日期'] == date_str].copy().sort_values(by='時間')
            
            # 根據全域 saved_ids 來決定是否勾選
            # 這是關鍵：勾選狀態來自「全域記憶」，而非篩選結果
            if "參加" not in day_df.columns:
                day_df.insert(0, "參加", day_df['id'].isin(st.session_state.saved_ids))
            
            edited_day_df = st.data_editor(
                day_df,
                column_config={
                    "參加": st.column_config.CheckboxColumn("參加", width="small"),
                    "時間": st.column_config.TextColumn("時間", width="small"),
                    "活動名稱": st.column_config.TextColumn("活動名稱", width="large"),
                    "地點": st.column_config.TextColumn("地點", width="medium"),
                    "主講人": st.column_config.TextColumn("主講人", width="medium"),
                    "類型": None, "主持人": None, "詳細內容": None, "備註": None, "來源": None, 
                    "id": None, "start_dt": None, "end_dt": None, "日期": None
                },
                hide_index=True,
                key=f"editor_{date_str}"
            )
            
            # --- 🔥 關鍵邏輯修正：同步更新 saved_ids ---
            # 我們不能只看 filter 後的結果，我們要「增量更新」
            
            # 1. 找出這個編輯器「當下顯示了哪些 ID」(Visible IDs)
            visible_ids = day_df['id'].tolist()
            
            # 2. 找出這個編輯器「當下被勾選的 ID」(Ticked IDs)
            ticked_ids = edited_day_df[edited_day_df["參加"] == True]['id'].tolist()
            
            # 3. 更新全域 saved_ids
            # 邏輯：
            # A. 把現在有勾的，確保加入 saved_ids
            # B. 把「本來有顯示」但「現在沒勾」的 (代表使用者取消了)，從 saved_ids 移除
            #    (注意：不能移除「因為篩選而沒顯示」的 ID)
            
            current_saved_set = set(st.session_state.saved_ids)
            
            # A. 加入新增的
            current_saved_set.update(ticked_ids)
            
            # B. 移除取消的 (只針對目前可見範圍)
            ids_to_remove = set(visible_ids) - set(ticked_ids)
            current_saved_set = current_saved_set - ids_to_remove
            
            # 寫回 Session State
            st.session_state.saved_ids = list(current_saved_set)

            # (UI 優化) 計算勾選數以控制焦點
            current_count = len(ticked_ids)
            current_selection_counts[date_str] = current_count
            if current_count != st.session_state.prev_selection_counts.get(date_str, 0):
                st.session_state.calendar_focus_date = date_str

st.session_state.prev_selection_counts = current_selection_counts
st.markdown("---")

# --- 2. 行程週曆 (邏輯修正版) ---
st.subheader("2. 行程週曆 🗓️")

# 🔥 關鍵修改：日曆的資料來源不再受 filtered_df 影響
# 而是直接從原始資料 (proc_df) 中抓取所有 saved_ids
# 這樣就算上面的篩選器把活動藏起來了，下面的日曆依然會顯示
final_selected = proc_df[
    (proc_df['id'].isin(st.session_state.saved_ids)) & 
    (proc_df['start_dt'].notnull())
]

# ... 以下接原本的日曆顯示程式碼 ...

# 顯示成功訊息 (如果有)
if st.session_state.save_success_msg:
    st.markdown(f'<div class="success-box">✅ {st.session_state.save_success_msg}</div>', unsafe_allow_html=True)
    # 顯示一次後清除，避免重整後還在 (需配合下次 rerun，這裡先暫留)
    st.session_state.save_success_msg = None 

c_cal_head, c_cal_save = st.columns([0.7, 0.3])
with c_cal_head:
    if len(final_selected) > 0:
        st.success(f"已顯示 {len(final_selected)} 場活動")

with c_cal_save:
    if st.session_state.is_guest:
        st.button("💾 儲存 (訪客無法使用)", disabled=True, use_container_width=True)
    else:
        if st.button("💾 儲存到雲端", type="primary", use_container_width=True):
            with st.spinner("正在同步..."):
                success, s_msg = save_user_schedule_to_cloud(st.session_state.user_id, final_selected)
                if success:
                    st.session_state.save_success_msg = "儲存成功！行程已更新"
                    st.session_state.saved_ids = final_selected['id'].tolist()
                    st.rerun() # 重新整理以顯示上方的大型成功訊息
                else:
                    st.error(f"儲存失敗: {s_msg}")

cal_events = []
for _, row in final_selected.iterrows():
    bg_color = "#3788d8" if str(row['來源']) == "國際書展" else "#ff9f43"
    cal_events.append({
        "title": f"{row['活動名稱']} @ {row['地點']}",
        "start": row['start_dt'].isoformat(),
        "end": row['end_dt'].isoformat(),
        "backgroundColor": bg_color,
        "borderColor": bg_color
    })

# 🔥 日曆優化設定：中文化、簡化標題、移除 Today
calendar_options = {
    "initialView": "timeGridDay", 
    "initialDate": st.session_state.calendar_focus_date,
    "headerToolbar": {
        "left": "prev,next", # 移除了 today
        "center": "title",
        "right": "timeGridWeek,timeGridDay,listDay" 
    },
    "buttonText": { # 按鈕中文化
        "timeGridWeek": "週",
        "timeGridDay": "日",
        "listDay": "表"
    },
    "titleFormat": {"month": "2-digit", "day": "2-digit"}, # 標題只顯示 02-04
    "slotMinTime": "09:00:00",
    "slotMaxTime": "21:00:00",
    "height": "600px", 
    "nowIndicator": True
}
calendar(events=cal_events, options=calendar_options, key=f"main_calendar")

st.markdown("---")

# --- 3. 匯出功能 ---
st.subheader("3. 帶走行程 🎒")
if not final_selected.empty:
    c1, c2, c3 = st.columns(3)
    with c1:
        cal_obj = Calendar()
        for _, row in final_selected.iterrows():
            e = Event()
            e.name = f"{row['活動名稱']} ({row['地點']})"
            if row['start_dt']: e.begin = row['start_dt'] - timedelta(hours=8)
            if row['end_dt']: e.end = row['end_dt'] - timedelta(hours=8)
            e.location = str(row['地點'])
            cal_obj.events.add(e)
        st.download_button("📅 匯出手機行事曆 (.ics)", data=cal_obj.serialize(), file_name="tibe_2026.ics", mime="text/calendar")
    
    with c2:
        cols = ["日期", "時間", "活動名稱", "地點", "備註"]
        v_cols = [c for c in cols if c in final_selected.columns]
        csv_data = final_selected[v_cols].to_csv(index=False).encode('utf-8-sig')
        st.download_button("🖨️ 匯出表格 (.csv)", data=csv_data, file_name="tibe.csv", mime="text/csv")

    with c3:
        txt = ""
        for _, row in final_selected.sort_values(by=['日期','時間']).iterrows():
            txt += f"{row['日期']} {row['時間']} | {row['活動名稱']} @ {row['地點']}\n"
        st.download_button("💬 複製文字", data=txt, file_name="tibe.txt", mime="text/plain")

# ==========================================
# 隱私權與資料聲明
# ==========================================
st.markdown("<br><br>", unsafe_allow_html=True)
with st.expander("ℹ️ 隱私權與使用聲明 (Privacy Policy)", expanded=False):
    st.markdown("""
    **1. 資料儲存：**
    * 本應用程式僅在您選擇「登入」並按下「儲存」時，才會將您的行程資料儲存至中央資料庫。
    * 所有使用者資料集中管理，以「暱稱 (User_ID)」區分。
    
    **2. 訪客模式：**
    * 訪客模式下，您的所有操作僅保留在當前瀏覽器視窗中，關閉視窗後即自動清除。

    **3. 免責聲明：**
    * 本系統活動資料蒐集自書展官方網站與公開資訊，僅供參考。
    * 活動時間、地點若有變動，請以主辦單位現場公告為準。
    
    **4. 專案資訊：**
    * This app is a personal project designed for the 2026 Taipei International Book Exhibition.
    """)