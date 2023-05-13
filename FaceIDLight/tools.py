import tflite_runtime.interpreter as tflite
import cv2
import numpy as np
import os
import glob
from skimage.transform import SimilarityTransform
from FaceIDLight.helper import get_file
from scipy.spatial import distance
from sklearn.metrics.pairwise import cosine_distances


BASE_URL = "https://github.com/Martlgap/FaceIDLight/releases/download/v.0.1/"

FILE_HASHES = {
    "o_net": "768385d570300648b7b881acbd418146522b79b4771029bb2e684bdd8c764b9f",
    "p_net": "530183192e24f7cc86b6706e1eb600482c4ed4306399ac939c472e3957bae15e",
    "r_net": "5ec33b065eb2802bc4c2575d21feff1a56958d854785bc3e2907d3b7ace861a2",
    "mobileNet": "6c19b789f661caa8da735566490bfd8895beffb2a1ec97a56b126f0539991aa6",
    "resNet": "f4d8b0194957a3ad766135505fc70a91343660151a8103bbb6c3b8ac34dbb4e2",
    "sample_gallery": "9f43a83c89a8099e1f3aab75ed9531f932f1b392bea538d6afe52509587438d4",
}

class FaceID:
    def __init__(self, gal_dir: str = None, model_type: str = "mobileNet"):
        self.detector = FaceDetection()
        self.recognizer = FaceRecognition(model_type=model_type)
        self.gal_embs = []
        self.gal_names = []
        self.gal_faces = []
        self.gal_dir = (
            gal_dir
            if gal_dir is not None
            else get_file(BASE_URL + "sample_gallery.zip", FILE_HASHES["sample_gallery"], is_zip=True)
        )
        self.update_gallery()

    def update_gallery(self):
        files = glob.glob("{}/*.jpg".format(self.gal_dir)) + glob.glob("{}/*.png".format(self.gal_dir))
        for file in files:
            img = cv2.imread(file)
            # TODO check if image is too large!
            detections = self.detector.detect_faces(img)  # Must be BGR and float32 [0..255]
            if not detections:
                continue
            _, points, _ = detections[0]  # Only take highest-score face
            self.gal_names.append(os.path.basename(file).split(".")[0])
            face = self.detector.get_face(img, points)
            self.gal_faces.append(
                cv2.cvtColor(face.astype(np.float32) / 255, cv2.COLOR_BGR2RGB)
            )  # RGB and float32 [0..1]

        # Get all embeddings in parallel
        # TODO handle maximum number of parallel invoke
        self.gal_embs = self.recognizer.get_emb(np.asarray(self.gal_faces))[0]

    def recognize_faces(self, img):
        # Detect faces
        detections = self.detector.detect_faces(img)
        if not detections:
            return []

        # Get face images and embeddings
        faces = [cv2.cvtColor(self.detector.get_face(img, det[1]).astype(np.float32) / 255, cv2.COLOR_BGR2RGB) for det in detections]
        embs = self.recognizer.get_emb(np.asarray(faces))[0]

        # Identify faces
        ids = []
        for emb in embs:
            pred, dist, conf = self.recognizer.identify(np.expand_dims(emb, axis=0), self.gal_embs, thresh=0.6)
            name = self.gal_names[pred] if pred is not None else "Other"
            face_img = cv2.cvtColor(self.gal_faces[pred] * 255, cv2.COLOR_RGB2BGR) if pred is not None else None
            ids.append([name, face_img, dist, conf])

        # Convert face images to BGR format and combine with detections and IDs
        faces_ = [cv2.cvtColor(face * 255, cv2.COLOR_RGB2BGR) for face in faces]
        out = list(zip(faces_, detections, ids))

        return out


def tflite_inference(model, img):

    input_details = model.get_input_details()
    output_details = model.get_output_details()
    model.resize_tensor_input(input_details[0]["index"], img.shape)
    model.allocate_tensors()
    model.set_tensor(input_details[0]["index"], img.astype(np.float32))
    model.invoke()
    return [model.get_tensor(elem["index"]) for elem in output_details]


class FaceRecognition:
    def __init__(
        self,
        model_path: str = None,
        model_type: str = "mobileNet",
    ):
        if model_path is None:
            model_path = get_file(BASE_URL + model_type + ".tflite", FILE_HASHES[model_type])
        self.face_recognizer = tflite.Interpreter(model_path=model_path)

    def get_emb(self, img):
        return tflite_inference(self.face_recognizer, img)

    @staticmethod
    def verify(emb1, emb2, thresh):
        dist = distance.cosine(emb1, emb2)
        prediction = thresh > np.squeeze(dist, axis=-1)
        abs_diff = np.abs(thresh - dist)
        confidence = np.where(prediction, abs_diff, dist - thresh)
        confidence = np.clip(confidence, 0, 1)
        confidence = confidence / (2 * thresh) + 0.5
        return prediction, np.squeeze(dist, axis=-1), confidence


    @staticmethod
    def identify(emb_src, embs_gal, thresh=None):
        dists = np.sum(emb_src * embs_gal, axis=1)
        dists /= np.linalg.norm(emb_src) * np.linalg.norm(embs_gal, axis=1)
        dists = 1 - dists
        
        pred = dists.argmin()
        if thresh and dists[pred] > thresh:  # if OpenSet set prediction to None if above threshold
            idx_1 = dists != dists[pred]
            conf = (dists[idx_1].min() - dists[pred]) / (1.4 - thresh)
            dist = dists[idx_1].min()
            pred = None
        else:
            idx_1 = dists != dists[pred]
            conf = (dists[idx_1].min() - dists[pred]) / 1.4
            dist = dists[pred]
        
        return pred, dist, conf


class StageStatus:
    def __init__(self, pad_result: tuple = None, width=0, height=0):
        self.width, self.height = width, height
        self.dy, self.edy, self.dx, self.edx, self.y, self.ey, self.x, self.ex, self.tmp_w, self.tmp_h = [], [], [], [], [], [], [], [], [], []

        if pad_result is not None:
            self.update(pad_result)

    def update(self, pad_result: tuple):
        self.dy, self.edy, self.dx, self.edx, self.y, self.ey, self.x, self.ex, self.tmp_w, self.tmp_h = pad_result



class FaceDetection:
    def __init__(
        self,
        min_face_size: int = 40,
        steps_threshold: list = None,
        scale_factor: float = 0.7,
    ):
        if steps_threshold is None:
            steps_threshold = [0.6, 0.7, 0.7]  # original mtcnn values [0.6, 0.7, 0.7]
        self._min_face_size = min_face_size
        self._steps_threshold = steps_threshold
        self._scale_factor = scale_factor
        self.p_net = tflite.Interpreter(model_path=get_file(BASE_URL + "p_net.tflite", FILE_HASHES["p_net"]))
        self.r_net = tflite.Interpreter(model_path=get_file(BASE_URL + "r_net.tflite", FILE_HASHES["r_net"]))
        self.o_net = tflite.Interpreter(model_path=get_file(BASE_URL + "o_net.tflite", FILE_HASHES["o_net"]))

    def detect_faces(self, img):
        height, width, _ = img.shape
        stage_status = StageStatus(width=width, height=height)
        m = 12 / self._min_face_size
        min_layer = np.amin([height, width]) * m
        scales = self.__compute_scale_pyramid(m, min_layer)

        # We pipe here each of the stages
        total_boxes, stage_status = self.__stage1(img, scales, stage_status)
        total_boxes, stage_status = self.__stage2(img, total_boxes, stage_status)
        bboxes, points = self.__stage3(img, total_boxes, stage_status)

        # Transform to better shape and points now inside bbox
        detections = []
        for bbox, point, conf in zip(bboxes, points, bboxes[:, -1]):
            bbox_c = np.reshape(bbox[:-1], [2, 2]).astype(np.float32)
            point_c = np.reshape(point, [2, 5]).transpose().astype(np.float32)
            detections.append([bbox_c, point_c, conf.astype(np.float32)])
        return detections



    def __compute_scale_pyramid(self, m, min_layer):
        scales = []
        factor_count = 0

        while min_layer >= 12:
            scales += [m * np.power(self._scale_factor, factor_count)]
            min_layer = min_layer * self._scale_factor
            factor_count += 1

        return scales

    @staticmethod
    def __scale_image(image, scale: float):
        # Calculate the new height and width using the scale factor
        height, width, _ = image.shape
        width_scaled = int(width * scale)
        height_scaled = int(height * scale)

        # Resize the image using OpenCV
        im_data = cv2.resize(image, dsize=None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        # Normalize the image's pixels
        im_data_normalized = (im_data - 127.5) * 0.0078125

        return im_data_normalized


    @staticmethod
    def __generate_bounding_box(imap, reg, scale, t):

        stride = 2
        cellsize = 12

        imap = np.transpose(imap)
        dx1 = np.transpose(reg[:, :, 0])
        dy1 = np.transpose(reg[:, :, 1])
        dx2 = np.transpose(reg[:, :, 2])
        dy2 = np.transpose(reg[:, :, 3])

        y, x = np.where(imap >= t)

        if y.shape[0] == 1:
            dx1 = np.flipud(dx1)
            dy1 = np.flipud(dy1)
            dx2 = np.flipud(dx2)
            dy2 = np.flipud(dy2)

        score = imap[(y, x)]
        reg = np.transpose(np.vstack([dx1[(y, x)], dy1[(y, x)], dx2[(y, x)], dy2[(y, x)]]))

        if reg.size == 0:
            reg = np.empty(shape=(0, 3))

        bb = np.transpose(np.vstack([y, x]))

        q1 = np.fix((stride * bb + 1) / scale)
        q2 = np.fix((stride * bb + cellsize) / scale)
        boundingbox = np.hstack([q1, q2, np.expand_dims(score, 1), reg])

        return boundingbox, reg

    @staticmethod
    def __nms(boxes, threshold, method):
        if boxes.size == 0:
            return np.empty((0, 3))

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        s = boxes[:, 4]

        area = (x2 - x1 + 1) * (y2 - y1 + 1)
        sorted_s = np.argsort(s)

        pick = np.zeros_like(s, dtype=np.int16)
        counter = 0
        while sorted_s.size > 0:
            i = sorted_s[-1]
            pick[counter] = i
            counter += 1
            idx = sorted_s[0:-1]

            xx1 = np.maximum(x1[i], x1[idx])
            yy1 = np.maximum(y1[i], y1[idx])
            xx2 = np.minimum(x2[i], x2[idx])
            yy2 = np.minimum(y2[i], y2[idx])

            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)

            inter = w * h

            if method == "Min":
                o = inter / np.minimum(area[i], area[idx])
            else:
                o = inter / (area[i] + area[idx] - inter)

            sorted_s = sorted_s[np.where(o <= threshold)]

        pick = pick[0:counter]

        return pick

    @staticmethod
    def __pad(total_boxes, w, h):
        # compute the padding coordinates (pad the bounding boxes to square)
        tmp_w = (total_boxes[:, 2] - total_boxes[:, 0] + 1).astype(np.int32)
        tmp_h = (total_boxes[:, 3] - total_boxes[:, 1] + 1).astype(np.int32)
        numbox = total_boxes.shape[0]

        dx = np.ones(numbox, dtype=np.int32)
        dy = np.ones(numbox, dtype=np.int32)
        edx = tmp_w.copy().astype(np.int32)
        edy = tmp_h.copy().astype(np.int32)

        x = total_boxes[:, 0].copy().astype(np.int32)
        y = total_boxes[:, 1].copy().astype(np.int32)
        ex = total_boxes[:, 2].copy().astype(np.int32)
        ey = total_boxes[:, 3].copy().astype(np.int32)

        tmp = np.where(ex > w)
        edx.flat[tmp] = np.expand_dims(-ex[tmp] + w + tmp_w[tmp], 1)
        ex[tmp] = w

        tmp = np.where(ey > h)
        edy.flat[tmp] = np.expand_dims(-ey[tmp] + h + tmp_h[tmp], 1)
        ey[tmp] = h

        tmp = np.where(x < 1)
        dx.flat[tmp] = np.expand_dims(2 - x[tmp], 1)
        x[tmp] = 1

        tmp = np.where(y < 1)
        dy.flat[tmp] = np.expand_dims(2 - y[tmp], 1)
        y[tmp] = 1

        return dy, edy, dx, edx, y, ey, x, ex, tmp_w, tmp_h

    @staticmethod
    def __rerec(bbox):
        # convert bbox to square
        height = bbox[:, 3] - bbox[:, 1]
        width = bbox[:, 2] - bbox[:, 0]
        max_side_length = np.maximum(width, height)
        bbox[:, 0] = bbox[:, 0] + width * 0.5 - max_side_length * 0.5
        bbox[:, 1] = bbox[:, 1] + height * 0.5 - max_side_length * 0.5
        bbox[:, 2:4] = bbox[:, 0:2] + np.transpose(np.tile(max_side_length, (2, 1)))
        return bbox

    @staticmethod
    def __bbreg(boundingbox, reg):
        # calibrate bounding boxes
        if reg.shape[1] == 1:
            reg = np.reshape(reg, (reg.shape[2], reg.shape[3]))

        w = boundingbox[:, 2] - boundingbox[:, 0] + 1
        h = boundingbox[:, 3] - boundingbox[:, 1] + 1
        b1 = boundingbox[:, 0] + reg[:, 0] * w
        b2 = boundingbox[:, 1] + reg[:, 1] * h
        b3 = boundingbox[:, 2] + reg[:, 2] * w
        b4 = boundingbox[:, 3] + reg[:, 3] * h
        boundingbox[:, 0:4] = np.transpose(np.vstack([b1, b2, b3, b4]))
        return boundingbox

    def __stage1(self, image, scales: list, stage_status: StageStatus):
        total_boxes = np.empty((0, 9))
        status = stage_status

        for scale in scales:
            scaled_image = self.__scale_image(image, scale)

            img_x = np.expand_dims(scaled_image, 0)
            img_y = np.transpose(img_x, (0, 2, 1, 3))

            out = tflite_inference(self.p_net, img_y)

            out0 = np.transpose(out[0], (0, 2, 1, 3))
            out1 = np.transpose(out[1], (0, 2, 1, 3))

            boxes, _ = self.__generate_bounding_box(
                out1[0, :, :, 1].copy(),
                out0[0, :, :, :].copy(),
                scale,
                self._steps_threshold[0],
            )

            # inter-scale nms
            pick = self.__nms(boxes.copy(), 0.5, "Union")
            if boxes.size > 0 and pick.size > 0:
                boxes = boxes[pick, :]
                total_boxes = np.append(total_boxes, boxes, axis=0)

        numboxes = total_boxes.shape[0]

        if numboxes > 0:
            pick = self.__nms(total_boxes.copy(), 0.7, "Union")
            total_boxes = total_boxes[pick, :]

            regw = total_boxes[:, 2] - total_boxes[:, 0]
            regh = total_boxes[:, 3] - total_boxes[:, 1]

            qq1 = total_boxes[:, 0] + total_boxes[:, 5] * regw
            qq2 = total_boxes[:, 1] + total_boxes[:, 6] * regh
            qq3 = total_boxes[:, 2] + total_boxes[:, 7] * regw
            qq4 = total_boxes[:, 3] + total_boxes[:, 8] * regh

            total_boxes = np.transpose(np.vstack([qq1, qq2, qq3, qq4, total_boxes[:, 4]]))
            total_boxes = self.__rerec(total_boxes.copy())

            total_boxes[:, 0:4] = np.fix(total_boxes[:, 0:4]).astype(np.int32)
            status = StageStatus(
                self.__pad(total_boxes.copy(), stage_status.width, stage_status.height),
                width=stage_status.width,
                height=stage_status.height,
            )

        return total_boxes, status

    def __stage2(self, img, total_boxes, stage_status: StageStatus):
        num_boxes = total_boxes.shape[0]
        if num_boxes == 0:
            return total_boxes, stage_status

        # second stage
        tempimg = np.zeros(shape=(24, 24, 3, num_boxes))

        for k in range(0, num_boxes):
            tmp = np.zeros((int(stage_status.tmp_h[k]), int(stage_status.tmp_w[k]), 3))

            tmp[stage_status.dy[k] - 1 : stage_status.edy[k], stage_status.dx[k] - 1 : stage_status.edx[k], :] = img[
                stage_status.y[k] - 1 : stage_status.ey[k],
                stage_status.x[k] - 1 : stage_status.ex[k],
                :,
            ]

            if tmp.shape[0] > 0 and tmp.shape[1] > 0 or tmp.shape[0] == 0 and tmp.shape[1] == 0:
                tempimg[:, :, :, k] = cv2.resize(tmp, (24, 24), interpolation=cv2.INTER_AREA)

            else:
                return np.empty(shape=(0,)), stage_status

        tempimg = (tempimg - 127.5) * 0.0078125
        tempimg1 = np.transpose(tempimg, (3, 1, 0, 2))

        out = tflite_inference(self.r_net, tempimg1)

        out0 = np.transpose(out[0])
        out1 = np.transpose(out[1])

        score = out1[1, :]

        ipass = np.where(score > self._steps_threshold[1])

        total_boxes = np.hstack([total_boxes[ipass[0], 0:4].copy(), np.expand_dims(score[ipass].copy(), 1)])

        mv = out0[:, ipass[0]]

        if total_boxes.shape[0] > 0:
            pick = self.__nms(total_boxes, 0.7, "Union")
            total_boxes = total_boxes[pick, :]
            total_boxes = self.__bbreg(total_boxes.copy(), np.transpose(mv[:, pick]))
            total_boxes = self.__rerec(total_boxes.copy())

        return total_boxes, stage_status

    def __stage3(self, img, total_boxes, stage_status: StageStatus):
        num_boxes = total_boxes.shape[0]
        if num_boxes == 0:
            return total_boxes, np.empty(shape=(0,))

        total_boxes = np.fix(total_boxes).astype(np.int32)

        status = StageStatus(
            self.__pad(total_boxes.copy(), stage_status.width, stage_status.height),
            width=stage_status.width,
            height=stage_status.height,
        )

        tempimg = np.zeros((48, 48, 3, num_boxes))

        for k in range(0, num_boxes):

            tmp = np.zeros((int(status.tmp_h[k]), int(status.tmp_w[k]), 3))

            tmp[status.dy[k] - 1 : status.edy[k], status.dx[k] - 1 : status.edx[k], :] = img[
                status.y[k] - 1 : status.ey[k], status.x[k] - 1 : status.ex[k], :
            ]

            if tmp.shape[0] > 0 and tmp.shape[1] > 0 or tmp.shape[0] == 0 and tmp.shape[1] == 0:
                tempimg[:, :, :, k] = cv2.resize(tmp, (48, 48), interpolation=cv2.INTER_AREA)
            else:
                return np.empty(shape=(0,)), np.empty(shape=(0,))

        tempimg = (tempimg - 127.5) * 0.0078125
        tempimg1 = np.transpose(tempimg, (3, 1, 0, 2))

        out = tflite_inference(self.o_net, tempimg1)
        out0 = np.transpose(out[0])
        out1 = np.transpose(out[1])
        out2 = np.transpose(out[2])

        score = out2[1, :]

        points = out1

        ipass = np.where(score > self._steps_threshold[2])

        points = points[:, ipass[0]]

        total_boxes = np.hstack([total_boxes[ipass[0], 0:4].copy(), np.expand_dims(score[ipass].copy(), 1)])

        mv = out0[:, ipass[0]]

        w = total_boxes[:, 2] - total_boxes[:, 0] + 1
        h = total_boxes[:, 3] - total_boxes[:, 1] + 1

        points[0:5, :] = np.tile(w, (5, 1)) * points[0:5, :] + np.tile(total_boxes[:, 0], (5, 1)) - 1
        points[5:10, :] = np.tile(h, (5, 1)) * points[5:10, :] + np.tile(total_boxes[:, 1], (5, 1)) - 1

        if total_boxes.shape[0] > 0:
            total_boxes = self.__bbreg(total_boxes.copy(), np.transpose(mv))
            pick = self.__nms(total_boxes.copy(), 0.7, "Min")
            total_boxes = total_boxes[pick, :]
            points = points[:, pick]

        return total_boxes, points.transpose()

    @staticmethod
    def get_face(img, dst, target_size=(112, 112)):
        src = np.array(
            [
                [38.2946, 51.6963],
                [73.5318, 51.5014],
                [56.0252, 71.7366],
                [41.5493, 92.3655],
                [70.7299, 92.2041],
            ],
            dtype=np.float32,
        )
        tform = SimilarityTransform()
        tform.estimate(dst, src)
        tmatrix = tform.params[0:2, :]
        return cv2.warpAffine(img, tmatrix, target_size, borderValue=0.0)
