"""
Desktop Pet  -  a little robot that runs across the top of your screen.

Runs as a transparent, always-on-top overlay (Windows).
Click the robot to close it.

Tweak the constants below to change size / speed / height.
"""

import tkinter as tk

TRANSPARENT = "magenta"   # this exact colour becomes see-through (Windows)
SIZE = 100                # window box the robot is drawn in
SPEED = 6                 # pixels moved per frame (bigger = faster run)
FRAME_MS = 40             # milliseconds per frame (~25 fps)
TOP_MARGIN = 8            # distance from the very top of the screen


class Pet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)                 # no title bar / border
        self.root.attributes("-topmost", True)           # stay above windows
        self.root.attributes("-transparentcolor", TRANSPARENT)

        self.sw = self.root.winfo_screenwidth()
        self.x = -SIZE
        self.y = TOP_MARGIN
        self.step = 0

        self.root.geometry(f"{SIZE}x{SIZE}+{self.x}+{self.y}")
        self.canvas = tk.Canvas(self.root, width=SIZE, height=SIZE,
                                bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", lambda e: self.root.destroy())

        self.animate()

    def draw(self):
        c = self.canvas
        c.delete("all")
        bob = -3 if (self.step // 3) % 2 == 0 else 0     # little vertical bounce
        cx, cy = SIZE // 2, SIZE // 2 + bob

        # body
        c.create_rectangle(cx-22, cy-18, cx+22, cy+18,
                           fill="#4a4a55", outline="#20202a", width=2)
        # head
        c.create_rectangle(cx-14, cy-34, cx+14, cy-16,
                           fill="#5b5b6a", outline="#20202a", width=2)
        # antenna
        c.create_line(cx, cy-34, cx, cy-42, fill="#8a8aa0", width=2)
        c.create_oval(cx-3, cy-46, cx+3, cy-40, fill="#00e0ff", outline="")
        # glowing eyes
        c.create_oval(cx-9, cy-28, cx-3, cy-22, fill="#00e0ff", outline="")
        c.create_oval(cx+3, cy-28, cx+9, cy-22, fill="#00e0ff", outline="")
        # arms
        c.create_line(cx-22, cy-6, cx-30, cy+4, fill="#20202a", width=4)
        c.create_line(cx+22, cy-6, cx+30, cy+4, fill="#20202a", width=4)
        # legs - alternate positions to look like running
        if (self.step // 3) % 2 == 0:
            c.create_line(cx-10, cy+18, cx-17, cy+30, fill="#20202a", width=4)
            c.create_line(cx+10, cy+18, cx+14, cy+27, fill="#20202a", width=4)
        else:
            c.create_line(cx-10, cy+18, cx-14, cy+27, fill="#20202a", width=4)
            c.create_line(cx+10, cy+18, cx+17, cy+30, fill="#20202a", width=4)

    def animate(self):
        self.step += 1
        self.x += SPEED
        if self.x > self.sw:            # ran off the right edge -> loop back
            self.x = -SIZE
        self.root.geometry(f"+{self.x}+{self.y}")
        self.draw()
        self.root.after(FRAME_MS, self.animate)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Pet().run()
