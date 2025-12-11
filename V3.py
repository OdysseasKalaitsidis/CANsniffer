import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading, time, queue, datetime, random, struct
from decoder import DataDecoder

# ==============================================================================
# SERIAL MANAGER
# ==============================================================================
class SerialManager:
    def __init__(self, port, baud, q):
        self.port, self.baud, self.q = port, baud, q
        self.running, self.ser = False, None

    def start(self):
        try:
            # Attempt connection
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            self.running = True
            threading.Thread(target=self.loop, daemon=True).start()
            self.q.put(("SYS", f"Connected to {self.port} @ {self.baud}"))
            return True

        except ValueError as e:
            # Occurs if parameters are out of range (e.g. baud -1)
            self.q.put(("SYS", f"Config Error: Invalid Baud Rate or Parameter ({e})"))
            return False
            
        except serial.SerialException as e:
            # Occurs if port is busy, not found, or permissions denied
            self.q.put(("SYS", f"Serial Error: {self.port} unavailable or busy."))
            return False
            
        except Exception as e:
            # Catch-all for anything else
            self.q.put(("SYS", f"Critical Error: {e}"))
            return False

    def stop(self):
        self.running = False
        if self.ser: 
            try: self.ser.close()
            except: pass
        self.q.put(("SYS", "Disconnected"))

    def loop(self):
        while self.running:
            try:
                if self.ser.in_waiting:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        self.q.put(("DATA", (ts, line)))
                else:
                    time.sleep(0.005)
            except:
                self.running = False
                self.q.put(("SYS", "Serial Error: Connection lost"))

# ==============================================================================
# TEST SIMULATOR
# ==============================================================================
class TestGen:
    def __init__(self, q):
        self.q = q
        self.running = False
        self.rpm, self.rpm_dir, self.volt, self.temp = 0, 1, 400000, 30

    def start(self):
        self.running = True
        threading.Thread(target=self.loop, daemon=True).start()
        self.q.put(("SYS", "Sim Started"))

    def stop(self):
        self.running = False
        self.q.put(("SYS", "Sim Stopped"))

    def loop(self):
        while self.running:
            self.rpm += 40 * self.rpm_dir
            if self.rpm >= 6000 or self.rpm <= 0: self.rpm_dir *= -1
            self.temp = min(60, self.temp + 0.05)
            
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            rpm_h = struct.pack('<h', int(self.rpm)).hex().upper()
            tmp_h = struct.pack('<h', int(self.temp)).hex().upper()
            v_bytes = int(self.volt + random.randint(-500, 500)).to_bytes(6, 'big', signed=True)
            v_str = " ".join(f"{x:02X}" for x in v_bytes)

            msgs = [
                f"0x181 8 30 {rpm_h[:2]} {rpm_h[2:]} 00 00 00 00",
                f"0x181 8 49 {tmp_h[:2]} {tmp_h[2:]} 00 00 00 00",
                f"0x523 6 {v_str}"
            ]
            for m in msgs:
                self.q.put(("DATA", (ts, m)))
                time.sleep(0.005)
            time.sleep(0.1)

# ==============================================================================
# GUI
# ==============================================================================
class CANsnifferUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CAN Sniffer Pro")
        self.decoder = DataDecoder()
        self.q = queue.Queue()
        self.ser_mgr, self.test_gen = None, None
        self.stats = {}

        # --- CONTROLS ---
        tf = tk.Frame(root, pady=5, padx=5)
        tf.pack(fill="x")
        
        # Port Selection Area
        tk.Label(tf, text="Port:").pack(side="left")
          # 1. Port Dropdown
        self.cb_ports = ttk.Combobox(tf, width=15)
        self.cb_ports.pack(side="left", padx=2)

        # BAUD rate
        tk.Label(tf, text="Baud:").pack(side="left", padx=5)

        self.cb_baud = ttk.Combobox(tf, width=10)
        self.cb_baud['values'] = ["9600", "19200", "38400", "57600", "115200", "250000", "500000", "1000000"]
        self.cb_baud.current(0)   # default = 9600
        self.cb_baud.pack(side="left", padx=2)
                
      
        
        # 2. Refresh Button
        self.btn_refresh = tk.Button(tf, text="⟳", width=3, command=self.refresh_ports, bg="#f0f0f0")
        self.btn_refresh.pack(side="left", padx=2)
        
        # 3. Connect / Disconnect Buttons
        self.btn_con = tk.Button(tf, text="Connect", command=self.connect, bg="#ddffdd", width=10)
        self.btn_con.pack(side="left", padx=10)
        
        self.btn_dis = tk.Button(tf, text="Disconnect", command=self.disconnect, state="disabled", bg="#ffdddd", width=10)
        self.btn_dis.pack(side="left")
        
        # Sim Button
        self.btn_sim = tk.Button(tf, text="Start Sim", command=self.toggle_sim, bg="lightblue")
        self.btn_sim.pack(side="left", padx=20)
        
        # Utilities
        self.auto_scr = tk.BooleanVar(value=True)
        tk.Checkbutton(tf, text="Auto Scroll", variable=self.auto_scr).pack(side="right")
        tk.Button(tf, text="Clear Log", command=self.clear).pack(side="right", padx=5)

        # --- TABS ---
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=5, pady=5)
        f_dash, f_raw, f_log = ttk.Frame(nb), ttk.Frame(nb), ttk.Frame(nb)
        nb.add(f_dash, text="Dashboard"); nb.add(f_raw, text="Raw Stream"); nb.add(f_log, text="Decoded Log")

        # Dashboard Treeview
        cols = ("ID", "Name", "DLC", "Data", "Value", "Freq", "Count", "Time")
        self.tree = ttk.Treeview(f_dash, columns=cols, show="headings")
        vsb = ttk.Scrollbar(f_dash, command=self.tree.yview); self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True); vsb.pack(side="right", fill="y")
        for c in cols: 
            self.tree.heading(c, text=c)
            self.tree.column(c, width=250 if c=="Value" else 60 if c in ["ID","DLC"] else 120)

        # Text Widgets
        self.txt_raw = scrolledtext.ScrolledText(f_raw, height=20, font=("Consolas", 10), bg="black", fg="#00ff00")
        self.txt_raw.pack(fill="both", expand=True)
        self.txt_log = scrolledtext.ScrolledText(f_log, height=20, font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True)

        # Initialize
        self.refresh_ports()
        self.root.after(50, self.update_loop)

    def refresh_ports(self):
        """Scans for available COM ports and updates the dropdown."""
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.cb_ports['values'] = port_list
        if port_list:
            self.cb_ports.current(0)
        else:
            self.cb_ports.set('')
    
    def connect(self):
        port = self.cb_ports.get()
        if not port:
            messagebox.showerror("Error", "Please select a COM port.")
            return

        #  Baud Rate Validation & Fallback ---
        raw_baud = self.cb_baud.get()
        try:
            baud = int(raw_baud)
            # Optional: Check for realistic range
            if baud <= 0: raise ValueError("Negative Baud")
        except ValueError:
            # Fallback Logic
            baud = 9600
            self.cb_baud.set("9600") # Update UI to reflect change
            self.txt_log.insert(tk.END, f"SYS: Invalid baud '{raw_baud}'. Falling back to 9600.\n")
            messagebox.showwarning("Baud Rate Warning", 
                                   f"Invalid Baud Rate '{raw_baud}'.\nDefaulting to 9600.")
        # -------------------------------------------------

        # Disable UI to prevent double clicks
        self.btn_con.config(state="disabled")
        
        self.ser_mgr = SerialManager(port, baud, self.q)
        if self.ser_mgr.start():
            self.btn_dis.config(state="normal")
            self.cb_ports.config(state="disabled")
            self.btn_refresh.config(state="disabled")
            self.cb_baud.config(state="disabled")
        else:
            self.btn_con.config(state="normal")
            # Error message is already handled inside SerialManager via queue, 
            # but a popup here helps too.
            messagebox.showerror("Connection Error", f"Could not open {port}\n(Check log for details)")

    def disconnect(self):
        if self.ser_mgr:
            self.ser_mgr.stop()
            self.ser_mgr = None
        
        self.btn_con.config(state="normal")
        self.btn_dis.config(state="disabled")
        self.cb_ports.config(state="normal")
        self.btn_refresh.config(state="normal")
        self.cb_baud.config(state="normal")


    def toggle_sim(self):
        if not self.test_gen:
            self.test_gen = TestGen(self.q)
            self.test_gen.start()
            self.btn_sim.config(text="Stop Sim", bg="#ff9999")
            self.btn_con.config(state="disabled")
            self.cb_ports.config(state="disabled")
        else:
            self.test_gen.stop()
            self.test_gen = None
            self.btn_sim.config(text="Start Sim", bg="lightblue")
            self.btn_con.config(state="normal")
            self.cb_ports.config(state="normal")

    def update_loop(self):
        while not self.q.empty():
            type, content = self.q.get()
            if type == "DATA":
                ts, raw = content
                self.txt_raw.insert(tk.END, f"{ts} | {raw}\n")
                if self.auto_scr.get(): self.txt_raw.see(tk.END)
                self.parse_frame(ts, raw)
            elif type == "SYS":
                self.txt_log.insert(tk.END, f"SYSTEM: {content}\n")
                if self.auto_scr.get(): self.txt_log.see(tk.END)
        self.root.after(50, self.update_loop)

    def parse_frame(self, ts, line):
        try:
            parts = line.replace(",", " ").replace("ID:", "").replace("DATA:", "").split()
            if len(parts) < 2: return
            cid = "0x" + parts[0] if not parts[0].startswith("0x") else parts[0]
            data = parts[2:]
            
            dec = self.decoder.decode(cid, data)
            val_str = ", ".join([f"{k}: {v}" for k,v in dec.items()]) if isinstance(dec, dict) else str(dec)
            
            now = time.time()
            prev = self.stats.get(cid, {'c': 0, 't': now})
            freq = f"{1.0/(now - prev['t']):.1f} Hz" if (now - prev['t']) > 0 else "-"
            self.stats[cid] = {'c': prev['c'] + 1, 't': now}

            row = (cid, self.decoder.get_name(cid), parts[1], " ".join(data), val_str, freq, self.stats[cid]['c'], ts)
            if self.tree.exists(cid): self.tree.item(cid, values=row)
            else: self.tree.insert("", "end", iid=cid, values=row)

            self.txt_log.insert(tk.END, f"[{ts}] {cid}: {val_str}\n")
        except: pass

    def clear(self):
        self.txt_raw.delete(1.0, tk.END)
        self.txt_log.delete(1.0, tk.END)

if __name__ == "__main__":
    r = tk.Tk()
    r.geometry("1100x600")
    CANsnifferUI(r)
    r.mainloop()