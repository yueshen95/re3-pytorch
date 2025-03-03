import cv2
import numpy as np
import torch
import time
import argparse

import sys
import os
import os.path
sys.path.append(os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.path.pardir)))
from tracker.network import Re3Net
import utils.bb_util as bb_util
import utils.im_util as im_util
import utils.drawing as drawing

from constants import CROP_PAD
from constants import CROP_SIZE

MAX_TRACK_LENGTH = 4

class Re3Tracker(object):
    def __init__(self, model_path = 'checkpoint.pth'):
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.net = Re3Net().to(self.device)
        if model_path is not None:
            if self.device.type == "cpu":
                self.net.load_state_dict(torch.load(model_path, map_location=lambda storage, loc: storage))
            else:
                self.net.load_state_dict(torch.load(model_path))
        self.net.eval()
        self.tracked_data = {}

    def track(self, id, image, bbox = None):
        image = image.copy()

        if bbox is not None:
            lstm_state = None
            past_bbox = bbox
            prev_image = image
            forward_count = 0
        elif id in self.tracked_data:
            lstm_state, initial_state, past_bbox, prev_image, forward_count = self.tracked_data[id]
        else:
            raise Exception('Id {0} without initial bounding box'.format(id))

        cropped_input0, past_bbox_padded = im_util.get_cropped_input(prev_image, past_bbox, CROP_PAD, CROP_SIZE)
        cropped_input1, _ = im_util.get_cropped_input(image, past_bbox, CROP_PAD, CROP_SIZE)

        network_input = np.stack((cropped_input0.transpose(2,0,1),cropped_input1.transpose(2,0,1)))
        network_input = torch.tensor(network_input, dtype = torch.float)    
        
        with torch.no_grad():
            network_input = network_input.to(self.device)
            network_predicted_bbox, lstm_state = self.net(network_input, prevLstmState = lstm_state)

        if forward_count == 0:
            initial_state = lstm_state
            # initial_state = None
            
        prev_image = image

        predicted_bbox = bb_util.from_crop_coordinate_system(network_predicted_bbox.cpu().data.numpy()/10, past_bbox_padded, 1, 1)

        # Reset state
        if forward_count > 0 and forward_count % MAX_TRACK_LENGTH == 0:
            lstm_state = initial_state

        forward_count += 1

        if bbox is not None:
            predicted_bbox = bbox

        predicted_bbox = predicted_bbox.reshape(4)

        self.tracked_data[id] = (lstm_state, initial_state, predicted_bbox, prev_image, forward_count)
        
        return predicted_bbox

    def reset(self):
        self.tracked_data = {}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tracking with Re3Net.')
    parser.add_argument('-p', '--path', action='store', type=str)
    parser.add_argument('-b', '--init_bbox', action='store', type=str, help = "In string format: \"xmin ymin xmax ymax\" ")
    args = parser.parse_args()
    PATH = args.path
    
    start_bbox = np.array([float(i) for i in args.init_bbox.split()])
    
    paths = [PATH + f for f in os.listdir(PATH)]
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    tracker = Re3Tracker()
    img = cv2.imread(paths[0])

    image_size = (img.shape[1], img.shape[0])
    video_writer = cv2.VideoWriter('result.avi',cv2.VideoWriter_fourcc(*'DIVX'), 30, image_size)

    predicted_bbox = tracker.track(1, img, start_bbox)
    for i in range(1,len(paths)):
        img = cv2.imread(paths[i])
        predicted_bbox = tracker.track(1,img)
        patch = drawing.drawRect(img, predicted_bbox, 1, (255,0,0))
        video_writer.write(patch)
    video_writer.release()
