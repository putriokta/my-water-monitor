from flask import Flask
import pandas as pd
from pmdarima import auto_arima
import requests
import threading
import traceback
import time
import pytz
import warnings
import os

warnings.filterwarnings("ignore", category=FutureWarning)

app = Flask(__name__)

# === KONFIGURASI ===
TOKEN = "7724051850:AAFRc5UYlabkgAwriXHh51OeaNdXlGDRjUk"
CHAT_ID = "1027769170"
CHANNEL_ID = "2761831"
TIMEZONE = pytz.timezone("Asia/Makassar")

last_status_prediksi = ""
last_sent_time_prediksi = 0
last_status_aktual = ""
last_sent_time_aktual = 0
NOTIF_INTERVAL = 600  # 10 menit

# === AMBIL DATA ===
def ambil_data_thingspeak(jumlah_data=200):
    try:
        timestamp = int(time.time())
        url = f"https://api.thingspeak.com/channels/2761831/feeds.csv?results={jumlah_data}&_={timestamp}"
        df = pd.read_csv(url)
        df.rename(columns={'field1': 'pH', 'field2': 'suhu', 'created_at': 'waktu'}, inplace=True)
        df['waktu'] = pd.to_datetime(df['waktu'], utc=True).dt.tz_convert(TIMEZONE)
        df['pH'] = pd.to_numeric(df['pH'], errors='coerce')
        df['suhu'] = pd.to_numeric(df['suhu'], errors='coerce')
        df = df[['waktu', 'pH', 'suhu']].dropna()
        return df
    except Exception as e:
        print("❌ Gagal ambil data:", e)
        return pd.DataFrame()

# === TELEGRAM ===
def kirim_telegram(pesan):
    try:
        url = f"https://api.telegram.org/bot7724051850:AAFRc5UYlabkgAwriXHh51OeaNdXlGDRjUk/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": pesan, "parse_mode": "Markdown"}
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("📤 Telegram dikirim.")
        else:
            print("⚠️ Gagal kirim:", response.text)
    except Exception as e:
        print("❌ Error kirim Telegram:", e)

# === RULE BASE ===
def cek_rulebase(ph, suhu):
    if ph <= 6.5 or ph >= 8.9 or suhu <= 26 or suhu >= 29:
        return "🚨 Air mendekati ambang batas, harap melakukan pengecekkan kondisi air"
    return "✅ Air dalam kondisi normal"

# === DETEKSI + PREDIKSI + NOTIF ===
def deteksi_dan_prediksi(df):
    global last_status_prediksi, last_sent_time_prediksi, last_status_aktual, last_sent_time_aktual
    try:
        waktu_terakhir = df['waktu'].iloc[-1]
        data_ph = df['pH'].dropna()
        data_suhu = df['suhu'].dropna()
        aktual_ph = data_ph.iloc[-1]
        aktual_suhu = data_suhu.iloc[-1]

        if len(data_ph) < 60 or len(data_suhu) < 60:
            print("⚠️ Data tidak cukup.")
            return

        model_ph = auto_arima(data_ph, seasonal=False, suppress_warnings=True, stepwise=True)
        model_suhu = auto_arima(data_suhu, seasonal=False, suppress_warnings=True, stepwise=True)

        pred_ph = model_ph.predict(n_periods=60).tolist()
        pred_suhu = model_suhu.predict(n_periods=60).tolist()

        ph_60 = pred_ph[59]
        suhu_60 = pred_suhu[59]
        waktu_pred_60 = waktu_terakhir + pd.Timedelta(minutes=60)

        status_prediksi = cek_rulebase(ph_60, suhu_60)
        status_aktual = cek_rulebase(aktual_ph, aktual_suhu)

        waktu_sekarang = time.time()

        # Notif prediksi (level 1)
        if "🚨" in status_prediksi and (status_prediksi != last_status_prediksi or waktu_sekarang - last_sent_time_prediksi >= NOTIF_INTERVAL):
            pesan_prediksi = (
                f"🚨 *Peringatan Awal (Prediksi 1 Jam)* 🚨\n"
                f"📍 Waktu Aktual: {waktu_terakhir.strftime('%H:%M:%S')} WITA\n"
                f"pH Aktual: {aktual_ph:.2f} | Suhu Aktual: {aktual_suhu:.2f}°C\n"
                f"\n🔮 Prediksi 1 Jam ke Depan ({waktu_pred_60.strftime('%H:%M:%S')} WITA):\n"
                f"pH: {ph_60:.2f} | Suhu: {suhu_60:.2f}°C\n"
                f"\n{status_prediksi}"
            )
            kirim_telegram(pesan_prediksi)
            last_status_prediksi = status_prediksi
            last_sent_time_prediksi = waktu_sekarang
        else:
            print("✅ Tidak ada notifikasi prediksi baru atau interval belum terpenuhi.")

        # Notif aktual (level 2)
        if "🚨" in status_aktual and (status_aktual != last_status_aktual or waktu_sekarang - last_sent_time_aktual >= NOTIF_INTERVAL):
            pesan_aktual = (
                f"🔴 *Peringatan Kritis (Kondisi Aktual)* 🔴\n"
                f"📍 Waktu: {waktu_terakhir.strftime('%H:%M:%S')} WITA\n"
                f"pH: {aktual_ph:.2f} | Suhu: {aktual_suhu:.2f}°C\n"
                f"\n{status_aktual}"
            )
            kirim_telegram(pesan_aktual)
            last_status_aktual = status_aktual
            last_sent_time_aktual = waktu_sekarang
        else:
            print("✅ Tidak ada notifikasi aktual baru atau interval belum terpenuhi.")

    except Exception:
        traceback.print_exc()

# === LOOP TIAP 10 MENIT ===
def loop_monitoring():
    df = ambil_data_thingspeak(200)
    if not df.empty:
        deteksi_dan_prediksi(df)
    threading.Timer(600, loop_monitoring).start()  # tiap 10 menit

# === WEB UNTUK TAMPILAN MANUAL ===
@app.route('/')
def index():
    try:
        df = ambil_data_thingspeak(200)
        if df.empty:
            return "<p>⚠️ Data kosong.</p>"

        waktu_terakhir = df['waktu'].iloc[-1]
        data_ph = df['pH']
        data_suhu = df['suhu']
        aktual_ph = data_ph.iloc[-1]
        aktual_suhu = data_suhu.iloc[-1]

        model_ph = auto_arima(data_ph, seasonal=False, suppress_warnings=True, stepwise=True)
        model_suhu = auto_arima(data_suhu, seasonal=False, suppress_warnings=True, stepwise=True)

        pred_ph = model_ph.predict(n_periods=60).tolist()
        pred_suhu = model_suhu.predict(n_periods=60).tolist()

        ph_60 = pred_ph[59]
        suhu_60 = pred_suhu[59]
        waktu_pred_60 = waktu_terakhir + pd.Timedelta(minutes=60)

        status = cek_rulebase(ph_60, suhu_60)

        return f"""
        <h2>📊 Monitoring Kualitas Air</h2>
        <ul>
            <li>🕒 Waktu Aktual: <b>{waktu_terakhir.strftime('%Y-%m-%d %H:%M:%S')} (WITA)</b></li>
            <li>📌 Aktual → pH: <b>{aktual_ph:.2f}</b> | Suhu: <b>{aktual_suhu:.2f}°C</b></li>
            <li>🔮 Prediksi 1 Jam → pH: <b>{ph_60:.2f}</b> | Suhu: <b>{suhu_60:.2f}°C</b> @ {waktu_pred_60.strftime('%H:%M:%S')}</li>
            <li>📋 Status Prediksi: <b>{status}</b></li>
        </ul>
        """
    except Exception:
        traceback.print_exc()
        return "<p>❌ Terjadi error saat prediksi.</p>"

# === JALANKAN APP ===
if __name__ == '__main__':
    loop_monitoring()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
