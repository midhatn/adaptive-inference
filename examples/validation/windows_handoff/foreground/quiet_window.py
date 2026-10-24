"""An owned, idle foreground phase for the desktop qualification, not a benchmark."""
import os
import threading
import tkinter as tk

# No input injection, focus loop, model, busy worker or user-content collection.
done = threading.Event()
def watchdog():
    if not done.wait(1830):
        os._exit(124)
threading.Thread(target=watchdog, daemon=True).start()
window = tk.Tk()
window.title('Adaptive recovery idle window')
window.geometry('780x350')
window.configure(background='#101923')
label = tk.Label(window, text='Adaptive Inference: quiet foreground phase\n\n'
                 'This window intentionally performs no background work.\n'
                 'It provides a visible idle phase after the animation test.\n\n'
                 'Close this window to end the quiet phase.',
                 background='#101923', foreground='#ecf1f5', font=('Segoe UI', 15), padx=30, pady=55)
label.pack(expand=True)
window.after(1800000, window.destroy)
try:
    window.mainloop()
finally:
    done.set()
