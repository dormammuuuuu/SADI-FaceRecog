
import cv2
from FaceIDLight.camera import Camera
from FaceIDLight.tools import FaceID


# TODO Why fps is so low if multi face? Should be parallel!


class Demonstrator:
    def __init__(self, gal_dir: str = None, stream_id: int = 0, model_type: str = "mobileNet"):
        # Initialization
        self.cam = Camera(stream_id=stream_id)
        self.FaceID = FaceID(gal_dir=gal_dir, model_type=model_type)

        # Set OpenCV defaults
        self.color = (0, 0, 255)
        self.font = cv2.QT_FONT_NORMAL

    def annotate(self, img, results):
        num = 0
        for result in results:
            face, detections, ids = result
            (
                bbox,
                points,
                conf,
            ) = detections
            name, gal_face, dist, id_conf = ids
            
            # Bbox as int
            bbox = bbox.astype(int)

            # Point as int
            points = points.astype(int)

            # Add BoundingBox
            img = cv2.rectangle(img, tuple(bbox[0]), tuple(bbox[1]), self.color)

            # # Add LandmarkPoints
            # for point in points:
            #     img = cv2.circle(img, tuple(point), 5, self.color)

            # Add Confidence Value
            img = cv2.putText(
                img,
                "Detect-Conf: {:0.2f}%".format(conf * 100),
                (int(bbox[0, 0]), int(bbox[0, 1]) - 20),
                self.font,
                0.7,
                (0, 0, 255),
            )

            # # Add aligned face onto img
            # img[0 : face.shape[1], num : num + face.shape[0]] = face
            # # Subject
            # img = cv2.putText(img, "Subject", (num, 10), self.font, 0.4, (255, 255, 255))

            # Add Prediction, Distance and Confidence
            img = cv2.putText(
                img, "{}".format(name), (int(bbox[0, 0]), int(bbox[0, 1]) - 80), self.font, 0.7, (255, 255, 0)
            )
            img = cv2.putText(
                img,
                "Emb-Dist: {:0.2f}".format(dist),
                (int(bbox[0, 0]), int(bbox[0, 1] - 60)),
                self.font,
                0.7,
                self.color,
            )
            img = cv2.putText(
                img,
                "ID-Conf: {:0.2f} %".format(id_conf * 100),
                (int(bbox[0, 0]), int(bbox[0, 1] - 40)),
                self.font,
                0.7,
                self.color,
            )

            # # Add gal face onto img
            # if name != "Other":
            #     img[112 : 112 + gal_face.shape[1], num : num + gal_face.shape[0]] = gal_face
            #     # Match
            #     img = cv2.putText(img, "GalleryMatch", (num, 112 + 10), self.font, 0.4, (255, 255, 255))

            num += 112
        return img

    def identification(self, frame):
        results = self.FaceID.recognize_faces(frame)
        frame = self.annotate(frame, results)
        return frame

    def run(self):
        self.cam.screen(self.identification)