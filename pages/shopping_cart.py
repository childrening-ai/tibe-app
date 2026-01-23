import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
import datetime
import time
import re

# 設定頁面
st.set_page_config(page_title="掃碼購物車", page_icon="🛒", layout="wide")

st.title("🛒 2026 書展掃碼比價 & 採購清單")
st.markdown("輸入 ISBN，自動抓取資料。(雲端環境以 Google 資料為主，輔以快速查價連結)")

# --- 設定區 ---
SHEET_NAME = "2026國際書展採購清單"

# --- 1. 連接 Google Sheets ---
@st.cache_resource
def connect_to_sheet():
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
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        return None

# --- 2. 爬蟲：Google Books (主力，因為它不擋雲端 IP) ---
def search_google_books(isbn):
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
    try:
        res = requests.get(url, timeout=5).json()
        if "items" in res:
            info = res["items"][0]["volumeInfo"]
            return {
                "source": "Google",
                "書名": info.get("title", ""),
                "作者": ", ".join(info.get("authors", [])),
                "封面": info.get("imageLinks", {}).get("thumbnail", ""),
                "found": True
            }
    except:
        pass
    return {"found": False}

# --- 3. 搜尋邏輯整合 ---
def smart_book_search(isbn):
    if not isbn: return None
    clean_isbn = isbn.replace("-", "").replace(" ", "")
    
    # 預設結果
    result = {
        "書名": "", "作者": "", "ISBN": clean_isbn, 
        "封面": "", "定價": "", 
        "建檔時間": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "found": False,
        "source": "None"
    }

    # 只抓 Google Books (因為 Findbook/國圖 在雲端都會被擋，不如直接放棄，節省等待時間)
    g_data = search_google_books(clean_isbn)
    
    if g_data["found"]:
        result.update(g_data)
        result["found"] = True
    
    return result

# --- 主程式 ---
sheet = connect_to_sheet()
if not sheet:
    st.error(f"❌ 無法連接試算表！請檢查 `{SHEET_NAME}` 設定。")
    st.stop()

if 'manual_entry_mode' not in st.session_state:
    st.session_state.manual_entry_mode = False
if 'search_result' not in st.session_state:
    st.session_state.search_result = None

col1, col2 = st.columns([1, 2])

with col1:
    st.info("👇 輸入 ISBN")
    with st.form("isbn_form", clear_on_submit=False): 
        isbn_input = st.text_input("ISBN 條碼")
        submitted = st.form_submit_button("🔍 查詢")

    if submitted and isbn_input:
        with st.spinner("☁️ 搜尋資料庫中..."):
            res = smart_book_search(isbn_input)
            st.session_state.search_result = res
            st.session_state.manual_entry_mode = False # 重置手動模式

# --- 結果顯示區 ---
if st.session_state.search_result:
    res = st.session_state.search_result
    
    st.divider()
    
    # 情境 A: Google 有抓到書 (通常有圖、有書名，缺價格)
    if res['found']:
        st.success(f"✅ 找到書籍：{res['書名']}")
        
        with st.form("confirm_form"):
            c1, c2 = st.columns([1, 2])
            with c1:
                if res['封面']:
                    st.image(res['封面'], width=120)
                else:
                    st.markdown("🖼️ (無封面)")
                
                # 🔥 這裡是最重要的功能：快速查價按鈕 🔥
                # 既然程式爬不到，我們提供傳送門，讓使用者點一下就能看到價格
                st.markdown("---")
                st.caption("👇 點擊按鈕查價，再填入右側")
                
                # 博客來連結
                st.markdown(f'''
                    <a href="https://search.books.com.tw/search/query/key/{res['ISBN']}/adv_author/1/" target="_blank" style="text-decoration:none;">
                        <button style="width:100%; background-color:#F2F2F2; border:1px solid #ddd; padding:8px; border-radius:5px; cursor:pointer;">
                            🔍 查博客來
                        </button>
                    </a>
                    <br><br>
                    <a href="https://findbook.tw/book/{res['ISBN']}/price" target="_blank" style="text-decoration:none;">
                        <button style="width:100%; background-color:#F2F2F2; border:1px solid #ddd; padding:8px; border-radius:5px; cursor:pointer;">
                            🔍 查 Findbook 比價
                        </button>
                    </a>
                ''', unsafe_allow_html=True)

            with c2:
                new_title = st.text_input("書名", value=res['書名'])
                new_author = st.text_input("作者", value=res['作者'])
                # 價格欄位預設為空，等待使用者查完填入
                new_price = st.text_input("💰 價格 (請依查價結果填入)", value="")
                
                confirm_btn = st.form_submit_button("✅ 確認並加入清單")

                if confirm_btn:
                    save_img = res['封面']
                    new_row = [res['建檔時間'], new_title, new_author, res['ISBN'], new_price, "待購"]
                    sheet.append_row(new_row)
                    st.toast(f"🎉 已加入：{new_title}")
                    time.sleep(1)
                    st.session_state.search_result = None
                    st.rerun()

    # 情境 B: 完全找不到 (Google 也沒資料) -> 純手動模式
    else:
        st.warning("⚠️ 資料庫找不到此書 (可能是太新的書)。請手動輸入。")
        
        # 即使找不到書，也提供查價按鈕，方便使用者複製書名
        st.markdown(f'''
            👉 
            <a href="https://search.books.com.tw/search/query/key/{isbn_input}/adv_author/1/" target="_blank">查博客來</a>
            ｜
            <a href="https://findbook.tw/book/{isbn_input}/price" target="_blank">查 Findbook</a>
        ''', unsafe_allow_html=True)

        with st.form("manual_form"):
            m_title = st.text_input("書名")
            m_author = st.text_input("作者")
            m_price = st.text_input("價格")
            m_submit = st.form_submit_button("➕ 加入清單")
            
            if m_submit and m_title:
                sheet.append_row([
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    m_title, m_author, isbn_input, m_price, "待購"
                ])
                st.success("已手動加入！")
                st.session_state.search_result = None
                st.rerun()

# --- 清單顯示區 ---
st.divider()
st.subheader("📋 雲端同步清單")
try:
    records = sheet.get_all_records()
    if records:
        st.data_editor(pd.DataFrame(records), use_container_width=True, num_rows="dynamic")
    else:
        st.info("目前清單是空的")
        if st.button("建立標題列"):
            sheet.append_row(["建檔時間", "書名", "作者", "ISBN", "價格", "狀態"])
            st.rerun()
except:
    pass