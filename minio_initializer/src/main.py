import logging

from services.minio_service import MinioService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

def main():
    logging.info("Starting Minio Checks")
    minio_service = MinioService()

    try:
        logging.info("Waiting for Minio to be active...")
        minio_service.wait_for_minio()
        logging.info("Minio service active")
    except RuntimeError  as error:
        logging.error("Could not reach Minio", error)
        raise

    if minio_service.is_main_bucket_in_created():
        logging.info("Minio bucket exists")
        return

    logging.info("Minio bucket does not exist, attempting creation...")
    minio_service.create_bucket(bucket_name=minio_service.bucket_name)
    logging.info("created bucket")


if __name__ == "__main__":
    main()
