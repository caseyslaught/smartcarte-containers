import numpy as np
import torch


def model_fn(model_dir):
    model_path = os.path.join(model_dir, 'model.pth')
    model = torch.load(model_path)
    return model


def input_fn(request_body, request_content_type):
    if request_content_type == 'application/json':
        input_data = json.loads(request_body)
        image = np.array(input_data['data'])
    else:
        image = np.load(request_body)['data']
        
    image = np.expand_dims(image, 0) 
    image = torch.tensor(image)
    
    return image
    
    
def predict_fn(input_data, model):

    prediction = model.predict(image)       
    probabilities = torch.sigmoid(prediction).cpu().numpy()
    probabilities = probabilities[0, 0, :, :]
    binary_prediction = (probabilities >= 0.80).astype(bool)
    return binary_prediction


    
def output_fn(binary_prediction, response_content_type):
        
    if response_content_type == 'application/json':
        output_dict = {'data': output_data.tolist()}
        output_string = json.dumps(output_dict)
    else:
        output_array = np.savez_compressed(BytesIO(), data=output_data)['data']
        output_string = output_array.tobytes()

    return output_string


