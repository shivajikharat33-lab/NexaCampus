from logger import logger, log_audit

logger.info("Backend Started")
logger.error("Test Error")

log_audit(
    actor_email="admin@gmail.com",
    action="TEST"
)

print("Logger Working ✅")