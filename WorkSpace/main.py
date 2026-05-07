import cv2
import time
import mediapipe as mp
from camera import CameraStream
from detector import LandmarkerDetector
from visualizer import Visualizer

## 11
import facemodule as FaceModule

def main():
    # 1. 모델 먼저 로드 (성공 핵심 순서)
    detector = LandmarkerDetector()
    visualizer = Visualizer()

    ## 11
    face_module = FaceModule.FaceModule()
    
    # 2. 카메라 시작
    stream = CameraStream(src=0).start()
    prev_time = 0

    while True:
        frame = stream.read()
        if frame is None: continue

        curr_time = time.time()

        ## 11
        dt = curr_time - prev_time if prev_time != 0 else 0.0

        fps = 1 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
        prev_time = curr_time

        # 전처리 및 탐지
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        
        face_res, pose_res = detector.detect(mp_image)


        ## 11
        # 얼굴 피로도 feature 추출
        face_features = face_module.update(face_res, dt)

        ## 11
        # 모델 입력값으로 변환
        model_input = face_module.to_model_input(face_features)

        ## 11
        # 확인용 출력
        print(face_module.get_feature_names())
        print(model_input)


        # 시각화 및 출력
        visualizer.draw(frame, face_res, pose_res, fps)
        cv2.imshow("Threaded Detection", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            stream.stop()
            break

    detector.close()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()