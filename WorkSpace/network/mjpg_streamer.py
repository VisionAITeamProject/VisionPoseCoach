import time


class MjpgStreamer:
    def __init__(self, camera_manager, frame_interval=0.05):
        self.camera_manager = camera_manager
        self.frame_interval = frame_interval

    def frames(self):
        while True:
            jpeg_frame = self.camera_manager.get_jpeg_frame()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + jpeg_frame
                + b"\r\n"
            )
            time.sleep(self.frame_interval)

