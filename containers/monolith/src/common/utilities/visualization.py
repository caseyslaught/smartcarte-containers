import matplotlib.pyplot as plt
import rasterio



def save_image(data, dst_path, cmap):
    plt.imshow(data, cmap=cmap, interpolation="nearest")
    plt.savefig(dst_path)
    plt.clf()


def plot_tif(tif_path, dst_path, bands=1, cmap="RdYlGn"):
    
    with rasterio.open(tif_path) as src:
        data = src.read(bands, masked=True)
        
    if type(bands) == list:
        data = data.transpose((1, 2, 0))
        
    save_image(data, dst_path, cmap=cmap)


def plot_bands(data, bands=[2, 1, 0], ax=None, transpose=False, cmap="RdYlGn"):
    
    # fixme: how to plot multichanel with mask?
    
    if type(bands) == list:
        if transpose:
            data = data[bands, :, :]
            data = data.transpose((1, 2, 0))
        else:
            data = data[:, :, bands]
    elif type(bands) == int:
        data = data[bands, :, :]
    
    axis = ax if ax is not None else plt    
    axis.imshow(data, cmap=cmap, interpolation="nearest")