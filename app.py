from flask import Flask, render_template, jsonify, redirect
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import pytz
from time import time

app = Flask(__name__)

# Simpan riwayat missed blocks (bisa gunakan database atau in-memory)
missed_blocks_history = []

# Tambahkan di awal file, setelah inisialisasi app
last_block_status = "🟩" * 15  # Status awal
last_known_height = 0  # Tinggi blok terakhir
last_check_time = datetime.now()  # Waktu terakhir cek

def calculate_missed_blocks(uptime_data):
    """
    Menghitung jumlah missed blocks dari data uptime
    """
    if not uptime_data:
        return 0
        
    # Hitung total missed blocks
    total_missed = sum(1 for block in uptime_data if not block['signed'])
    return total_missed

def get_consensus_info():
    url = "https://api.testnet.storyscan.app/utilities/consensus-info"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": f"Error mengambil data consensus: {e}"}

def format_tokens(tokens):
    """
    Menyederhanakan format tokens
    Contoh: 20137216001 -> 20.1B
    """
    try:
        tokens = int(tokens)
        if tokens >= 1_000_000_000:  # Miliar
            return f"{tokens/1_000_000_000:.1f}B"
        elif tokens >= 1_000_000:  # Juta
            return f"{tokens/1_000_000:.1f}M"
        else:
            return str(tokens)
    except:
        return "0"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/monitoring')
def monitoring():
    return render_template('monitoring.html')

@app.route('/installation')
def installation():
    return render_template('installation.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/api/status')
def get_status():
    try:
        response = requests.get("https://api.testnet.storyscan.app/validators/active")
        response.raise_for_status()
        validators = response.json()
        
        all_validators = []
        
        total_validator_active = sum(
            1 for v in validators 
            if v.get("votingPowerPercent", 0) > 0 
            and not v.get("signingInfo", {}).get("tombstoned", False)
        )
        
        global last_block_status, last_known_height, last_check_time
        
        current_time = datetime.now()
        # Cek apakah sudah 1.2 detik sejak update terakhir
        if (current_time - last_check_time).total_seconds() >= 1.2:
            # Geser blok lama ke kiri dan tambah blok baru
            last_block_status = last_block_status[1:] + "🟩"
            last_check_time = current_time
            
        # Buat efek kedip berdasarkan waktu
        current_time = int(time())
        if current_time % 2 == 0:  # Kedip setiap 1 detik
            block_status = "🟩" * 10
        else:
            block_status = "⬜" * 10
        
        for validator in validators:
            is_active = (
                validator.get("status") == "BOND_STATUS_BONDED" or 
                validator.get("bondStatus") == "BOND_STATUS_BONDED"
            )
            
            last_sync_height = validator.get('uptime', {}).get('historicalUptime', {}).get('lastSyncHeight', 'Unavailable')
            
            # Ambil data blok dari validator
            blocks_data = validator.get('uptime', {}).get('blocks', [])[-19:]  # Ambil 19 blok (sisa 1 untuk blok baru)
            current_height = validator.get('uptime', {}).get('historicalUptime', {}).get('lastSyncHeight', 0)
            
            # Cek status setiap blok
            block_status = ""
            for block in blocks_data:
                block_height = block.get('height')
                
                # Jika ini blok terbaru
                if block_height == current_height:
                    block_status += "⬜"  # Putih karena baru
                else:
                    # Blok lama, cek statusnya
                    if not block.get('signed'):
                        block_status += "🟥"  # MISS
                    elif block.get('proposed'):
                        block_status += "🟦"  # PROPOSED
                    else:
                        block_status += "🟩"  # SIGNED
            
            # Tambah blok baru yang berkedip
            current_time = datetime.now().second
            if current_time % 2 == 0:
                block_status += "⬜"  # Blok baru berkedip putih
            else:
                block_status += "🟩"  # Saat tidak kedip, tampilkan hijau
            
            # Jika kurang dari 20, tambahkan hijau
            while len(block_status) < 20:
                block_status += "🟩"
            
            status_data = {
                "status_icon": "🟢" if is_active else "🔴",
                "chain": "odyssey-0",
                "block": last_sync_height,
                "miss": calculate_missed_blocks_from_uptime(validator.get('uptime', {})),
                "moniker": validator.get("description", {}).get("moniker", "Unknown"),
                "uptime": f"{float(validator.get('uptime', {}).get('windowUptime', {}).get('uptime', 0)) * 100:.2f}%",
                "rank": validator.get("rank", "N/A"),
                "voting": f"{float(validator.get('votingPowerPercent', 0)) * 100:.2f}%",
                "blocks_row1": block_status[:10],  # 10 blok pertama
                "blocks_row2": block_status[10:],  # 10 blok kedua
                "update": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "total_active": total_validator_active,
                "tokens": format_tokens(validator.get('tokens', 0)),  # Format baru
                "operatorAddress": validator.get("operator_address", ""),
            }
            all_validators.append(status_data)
            
        return jsonify({
            "validators": all_validators,
            "total_active": total_validator_active,  # Sekarang akan menampilkan jumlah yang benar
            "current_block": validators[0].get('uptime', {}).get('historicalUptime', {}).get('lastSyncHeight', 'N/A') if validators else 'N/A',
            "update_time": datetime.now().strftime("%m/%d/%Y, %I:%M:%S %p")
        })
        
    except Exception as e:
        print("Error:", str(e))
        return jsonify({"error": str(e)})

def calculate_missed_blocks_from_uptime(uptime_data):
    if not uptime_data or 'historicalUptime' not in uptime_data:
        return 0
        
    historical = uptime_data['historicalUptime']
    total_blocks = historical.get('lastSyncHeight', 0) - historical.get('earliestHeight', 0)
    success_blocks = historical.get('successBlocks', 0)
    
    missed_blocks = total_blocks - success_blocks
    return missed_blocks if missed_blocks > 0 else 0

if __name__ == "__main__":
    app.run(debug=True)
