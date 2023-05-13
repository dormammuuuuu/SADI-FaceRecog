import threading
import cv2
import time


class Camera:
    def __init__(self, stream_id=0):
        self.stream_id = stream_id
        self.currentFrame = None
        self.ret = False
        self.stop = False
        self.capture = cv2.VideoCapture(stream_id)

        # Create a thread to continuously update the frame
        self.update_frame_thread = threading.Thread(target=self.update_frame)
        self.update_frame_thread.daemon = True
        self.update_frame_thread.start()

    # Continually updates the frame
    def update_frame(self):
        while not self.stop:
            self.ret, self.currentFrame = self.capture.read()
            while self.currentFrame is None:  # Continually grab frames until we get a good one
                self.capture.read()

    # Get current frame
    def get_frame(self):
        return self.ret, self.currentFrame

    def screen(self, function):
        window_name = "Streaming from {}".format(self.stream_id)
        cv2.namedWindow(window_name)
        last = 0
        while not self.stop:
            ret, frame = self.get_frame()
            if ret:
                frame = function(frame)
                frame = cv2.putText(
                    frame,
                    "FPS{:5.1f}".format(1 / (time.time() - last)),
                    (frame.shape[1] - 80, 30),
                    cv2.FONT_HERSHEY_PLAIN,
                    1,
                    (0, 255, 0),
                )
                last = time.time()
                cv2.imshow(window_name, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                self.stop = True

        # Join the thread to ensure that it terminates cleanly
        self.update_frame_thread.join()
        cv2.destroyWindow(window_name)
        self.capture.release()
