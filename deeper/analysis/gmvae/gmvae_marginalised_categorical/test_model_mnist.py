#%%
from pathlib import Path
import tensorflow as tf
import numpy as np
from tqdm import tqdm

# tf.enable_v2_behavior()
# tf.enable_eager_execution()
tf.random.set_seed(123154)
# tf.keras.backend.set_floatx('float64')

import numpy as np
from deeper.models.gmvae.gmvae_marginalised_categorical import model as model
from deeper.models.gmvae.gmvae_marginalised_categorical.utils import (
    chain_call,
    chain_call_dataset,
    purity_score,
)
from deeper.models.gmvae.gmvae_marginalised_categorical.train import train, train_even, train_known
from sklearn.metrics import confusion_matrix, classification_report
from sklearn.mixture import GaussianMixture
from sklearn.cluster import MiniBatchKMeans
from sklearn.preprocessing import OneHotEncoder
from deeper.utils.metrics import purity_score
import deeper.utils.cooling as cooling

print("tensorflow gpu available {}".format(tf.test.is_gpu_available()))

#%% Checlk whether the log directory exists. If it does not create it and empty
logfolder = Path("./logs/test_model/")
# if logpathis_dir():

gpus = tf.config.experimental.list_physical_devices("GPU")
if gpus:
    try:
        # Currently, memory growth needs to be the same across GPUs
        for gpu in gpus:
            # tf.config.experimental.gpu.set_per_process_memory_fraction(0.9)
            tf.config.experimental.set_memory_growth(gpu, True)
            tf.config.experimental.set_synchronous_execution(True)
            # tf.config.experimental.set_per_process_memory_fraction( 0.9)
        logical_gpus = tf.config.experimental.list_logical_devices("GPU")
        print(len(gpus), "Physical GPUs,", len(logical_gpus), "Logical GPUs")
    except RuntimeError as e:
        # Memory growth must be set before GPUs have been initialized
        print(e)

#%% Load MNIST and make it binary encoded
mnist = tf.keras.datasets.mnist
(X_train, y_train), (X_test, y_test) = mnist.load_data()
X_train, X_test = X_train / 255.0, X_test / 255.0
X_train = X_train.reshape(X_train.shape[0], 28 * 28)
X_test = X_test.reshape(X_test.shape[0], 28 * 28)
X_train = (X_train > 0.5).astype(float)
X_test = (X_test > 0.5).astype(float)


#%% Instantiate the model
from importlib import reload

model = reload(model)

initial_learning_rate = 1e-3
lr_schedule = tf.keras.optimizers.schedules.ExponentialDecay(
    initial_learning_rate, decay_steps=1000, decay_rate=0.8, staircase=True
)

params = {
    "components": len(set(y_train)),
    "input_dimension": X_train.shape[1],
    "embedding_dimensions": [512, 512],
    "latent_dimensions": 64,
    "mixture_embedding_dimensions": [512, 512],
    "mixture_latent_dimensions": 64,
    "embedding_activations": tf.nn.relu,
    "kind": "binary",
    "learning_rate": initial_learning_rate,
    "gradient_clip": 1e10,
    "bn_before": False,
    "bn_after": False,
    "categorical_epsilon": 1e-12,
    "reconstruction_epsilon": 1e-12,
    "latent_epsilon": 1e-12,
    "latent_prior_epsilon": 1e-12,
    "z_kl_lambda": 1.0,
    "c_kl_lambda": 1.0,
    "cat_latent_bias_initializer": None,
    "optimizer": tf.keras.optimizers.Adam(1e-2, epsilon=1e-16),
    "connected_weights": False,
    # "optimizer":tf.keras.optimizers.SGD(
    #    1e-3,
    #    #momentum=0.99
    # ),
    "categorical_latent_embedding_dropout": 0.2,
    "mixture_latent_mu_embedding_dropout": 0.2,
    "mixture_latent_var_embedding_dropout": 0.2,
    "mixture_posterior_mu_dropout": 0.2,
    "mixture_posterior_var_dropout": 0.2,
    "recon_dropouut": 0.2,
    #'latent_fixed_var': 10.0,
}

param_string = "__".join([str(k) + "_" + str(v) for k, v in params.items()])

m1 = model.Gmvae(**params)

#%%

res = m1.call(X_test)


#%% Examine SOftmax Distribution
import pandas as pd

logits, prob = m1.graph_qy_g_x.call(X_test, training=False)

logit_df = pd.DataFrame()
for col in range(logits.shape[1]):
    temp_df = pd.DataFrame({"value": logits[:, col]})
    temp_df["k"] = str(col)
    logit_df = logit_df.append(temp_df, ignore_index=True)
import seaborn as sns

logit_df = logit_df.loc[logit_df.value > np.log(0.01)]

sns.violinplot(data=logit_df, y="value", x="k")

# Plot the correct prediction densities

print("Purity Score {}".format(purity_score(y_test, logits.numpy().argmax(1))))


# confusion matrix of the classification
# for each caategory map the appropriate prediction
confusion_matrix(y_test, np.argmax(m1.predict(X_test), 1))


#%% Create a kmeans clustering dist

ohe = OneHotEncoder()
km = MiniBatchKMeans(10)
km_y_train_idx = km.fit_predict(X_train)
km_y_test_idx = km.predict(X_test)
purity_score(y_train, km_y_train_idx)
km_y_train = ohe.fit_transform(km_y_train_idx.reshape(-1, 1)).todense()
km_y_test = ohe.transform(km_y_test_idx.reshape(-1, 1)).todense()

print(
    "Niave clustering Purity Score {}".format(
        purity_score(y_test, km_y_test_idx)
    )
)

#%% Pretrain the model. Each layer individually.
for i in tqdm(range(500)):
    idx = np.random.choice(len(X_train), 100)
    m1.pretrain_categories_step(X_train[idx], np.array(km_y_train[idx]))

#%% validate the model now matches the pretrained dist
confusion_matrix(y_test, km_y_test_idx)

for i in tqdm(range(10)):
    idx = np.random.choice(len(X_train), 100)
    m1.pretrain_step(X_train[idx], 10)


#%% setup cooling for trainign loop constants

# z_cooling = cooling.CyclicCoolingRegime(cooling.linear_cooling, 1e-1, 1, 25, 35)
# y_cooling = cooling.CyclicCoolingRegime(cooling.linear_cooling, 10.0, 1.0, 25, 35)

z_cooling = lambda: 1.0
y_cooling = lambda: 1.0


#%% Pretrain the encoder-decoders
if True:
    train_even(
        m1,
        X_train,
        y_train,
        X_test,
        y_test,
        num=100,
        samples=1,
        epochs=25,
        iter_train=1,
        num_inference=1000,
        save=None,#"model_w",
        batch=True,
        beta_z_method=z_cooling,
        beta_y_method=y_cooling,
    )

    latent = chain_call(m1.latent_sample, X_train, 100)
    pretrain_gmm = GaussianMixture(10).fit(latent)
    pretrain_pred = pretrain_gmm.predict(latent)

    train_known(
        m1,
        pretrain_pred,
        X_train,
        y_train,
        X_test,
        y_test,
        num=100,
        samples=1,
        epochs=5,
        iter_train=1,
        num_inference=1000,
        save=None,#"model_w",
        batch=True,
        beta_z_method=z_cooling,
        beta_y_method=y_cooling,
    )




#%% Train the model
# with tf.device('/gpu:0'):
train(
    m1,
    X_train,
    y_train,
    X_test,
    y_test,
    num=100,
    samples=1,
    epochs=1000,
    iter_train=1,
    num_inference=1000,
    save="model_w",
    batch=True,
    beta_z_method=z_cooling,
    beta_y_method=y_cooling,
)


#%% Plot the latent space

# res_tensors = chain_call(m1.call, X_test, 1000)
res_tensors = m1(X_test)
mixture_prob = res_tensors[1]
mixture_latent_vectors = res_tensors[5]
# latent_vectors =

#%%
# verify sklearn gaussian mixture?
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from matplotlib import pyplot as plt
from sklearn.mixture import GaussianMixture

pca = PCA(2)
# pca = TSNE(2)
X_pca = pca.fit_transform(latent_vectors)
kmeans = GaussianMixture(10, tol=1e-6, max_iter=1000)
pred = kmeans.fit_predict(X_pca)
print(purity_score(y_test, pred))

df_latent = pd.DataFrame(
    {
        "x1": X_pca[:, 0],
        "x2": X_pca[:, 1],
        "cat": ["pred_{}".format(i) for i in y_test],
        "kmeans": ["pred_{}".format(i) for i in pred],
    }
)
plt.figure(figsize=(10, 10))
sns.scatterplot(data=df_latent, x="x1", y="x2", hue="cat")

plt.figure(figsize=(10, 10))
sns.scatterplot(data=df_latent, x="x1", y="x2", hue="kmeans")


#%% Display an original image
from matplotlib.pyplot import imshow
from matplotlib import pyplot as plt

k = 7


# plt.subplot()
# imshow(image, cmap='gray')

w = h = 28
fig, axes = plt.subplots(2, 10, figsize=(25, 5))
for j in range(10):
    image = X_test[k + j].reshape(w, h)
    # imshow(image, cmap='gray')

    # Display a predicted imgage
    image2 = (
        tf.add_n(
            [
                (
                    tf.cast(
                        mixture_prob[k, i, None, None]
                        * res_tensors[9][i, k + j, :],
                        tf.float32,
                    )
                )
                for i in range(10)
            ]
        )
        .numpy()
        .reshape(w, h)
    )

    axes[0, j].imshow(image)
    axes[1, j].imshow(image2)


# %%
