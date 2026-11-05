# Application images

Only customized applications are included. Each directory contains its
Dockerfile, changed source files and required build inputs. Source builds fetch
the fixed upstream revision during `docker build`; the repository contains no
upstream checkout.

Payment images extend published upstream images pinned by digest. Bank images
compile from source and use the public Java and nginx runtime images. No build
depends on an earlier H20 or H22 local image. Licenses accompany the changes.

From this directory:

```sh
docker build -t handsonsecurity/emuvista-payment-app:1.0 payment-app
docker build -t handsonsecurity/emuvista-payment-accounting:1.0 payment-accounting
docker build -t handsonsecurity/emuvista-bank-consumer:1.0 bank-consumer
docker build -t handsonsecurity/emuvista-bank-frontend:1.0 bank-frontend
```

After a source change, rebuild that image and recreate its example container.
Bundles reference these image names. Other application and infrastructure
images keep their existing references.

To use your Docker Hub account, change the image tag and the matching Bundle
image reference. Publishing with `docker push` is separate from local builds.
