import os
import tensorflow as tf
import numpy as np
from tqdm.autonotebook import tqdm
from sklearn.metrics import adjusted_mutual_info_score
from .utils import chain_call, plot_latent
from deeper.utils.tensorboard import plot_to_image


def train(
    model,
    X_train,
    X_test,
    num,
    samples,
    epochs,
    iter_train,
    num_inference,
    batch=False,
    verbose=1,
    save=None,
    save_results=None,
    beta_z_method=lambda: 1.0,
    tensorboard="./logs",
):

    # t1 = tqdm(total=epochs, position=0)
    # t2 = tqdm(total=int(X_train.shape[0] // num), position=1, leave=False)

    if tensorboard is not None:
        summary_writer = tf.summary.create_file_writer(tensorboard)

    if save_results is not None:

        header_str = ("{:<10}\t{:<10}\t{:<10}\t{:<10}\t{:<10}").format(
            "epoch", "beta_z", "loss", "likelih", "z-prior",
        )

        save_results = os.path.join(os.path.abspath(save_results))

        if not os.path.exists(save_results):
            with open(save_results, "w") as results_file:
                results_file.write(header_str)

    tqdm.write(header_str)

    for i in range(epochs):

        # Setup datasets
        dataset_train = (
            tf.data.Dataset.from_tensor_slices(X_train)
            .repeat(iter_train)
            .shuffle(X_train.shape[0])
            .batch(num)
        )

        iter = model.cooling_distance
        beta_z = beta_z_method()

        for x in dataset_train:
            model.train_step(
                # random sampling
                tf.cast(
                    tf.greater(
                        tf.cast(x, tf.float64),
                        tf.cast(tf.random.uniform(tf.shape(x), 0, 1), x.dtype),
                    ),
                    x.dtype,
                ),
                samples=samples,
                batch=batch,
                beta_z=beta_z,
            )

        # for i in range(iter):
        #    idx=np.random.choice(len(X_train), num)
        #    model.train_step(X_train[idx])
        #    t2.update(1)
        # t2.close()

        if i % verbose == 0:
            # Evaluate training metrics
            ##recon, z_ent, y_ent = chain_call(model.entropy_fn, X_train, num_inference)
            recon, z_ent = chain_call(model.entropy_fn, X_train, num_inference)

            recon = np.array(recon).mean()
            z_ent = np.array(z_ent).mean()

            loss = -(recon + z_ent)

            value_str = "{:d}\t{:10.5f}\t{:10.5f}\t{:10.5f}\t{:10.5f}".format(
                int(model.cooling_distance), beta_z, loss, recon, z_ent,
            )

            if save_results is not None:
                with open(save_results, "a") as results_file:
                    results_file.write("\n" + value_str)

            tqdm.write(value_str)

            if save is not None:
                model.save_weights(save, save_format="tf")

            model.increment_cooling()

            if tensorboard is not None:
                # plot latent space
                latent_vectors = chain_call(
                    model.latent_sample, X_test, num_inference
                )
                plt_latent_true = plot_latent(latent_vectors, y_test, idx_te)

                with summary_writer.as_default():
                    tf.summary.scalar("beta_z", beta_z, step=iter)
                    tf.summary.scalar("loss", loss, step=iter)
                    tf.summary.scalar("likelihood", recon, step=iter)
                    tf.summary.scalar("z_prior_entropy", z_ent, step=iter)
                    tf.summary.image(
                        "latent", plot_to_image(plt_latent_true), step=iter
                    )

        # t1.update(1)
        # t2.n = 0
        # t2.last_print_n = 0
        # t2.refresh()
    # t1.close()
