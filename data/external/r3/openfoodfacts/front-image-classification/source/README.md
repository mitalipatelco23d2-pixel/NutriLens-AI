---
dataset_info:
  features:
  - name: image_id
    dtype: string
  - name: image
    dtype: image
  - name: width
    dtype: int64
  - name: height
    dtype: int64
  - name: meta
    struct:
    - name: barcode
      dtype: string
    - name: off_image_id
      dtype: string
    - name: image_url
      dtype: string
  - name: category_id
    dtype: int64
  - name: category_name
    dtype: string
  splits:
  - name: train
    num_bytes: 234663276
    num_examples: 1000
  - name: test
    num_bytes: 96022334
    num_examples: 400
  download_size: 330223452
  dataset_size: 330685610
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
  - split: test
    path: data/test-*
license: agpl-3.0
task_categories:
- image-classification
tags:
- food
size_categories:
- 1K<n<10K
---

# Front image classification dataset

This dataset contains Open Food Facts images, each assigned with one of the two following classes:

- `front` (ID 0)
- `other` (ID 1)

Front images are the "default" image of a product, displayed on Open Food Facts product page. A front image is most of the time a photo of the front side of the product packaging. It's useful to be able to detect front images so that we can update the front image with a newer version (when the packaging changes for example).

Random images were fetched from Open Food Facts using the Parquet export, and pre-annotated with their class, depending on whether the image was selected as a front image or not.
The CLI command used to generate the pre-annotated dataset can be found [here](https://github.com/openfoodfacts/openfoodfacts-ai/blob/dbbec40a3d964124cd7c8d838023be4a10d6c0be/front-image-classification/cli.py#L115).

The dataset was then manually reviewed and corrected.
