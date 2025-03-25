Configuration File: [Github link](https://github.com/sdn-sense/end-to-end-tester/blob/main/packaging/endtoend.yaml)

# Test Process:
- Generates unique pairs for all valid endpoints (see `entries` key in the configuration file).
- Runs every 12 hours (or as configured by `runInterval`).
- Submits a new path request using the template:  
  - **1Gb Guaranteed Capped**  
  - **Assign IPv6 address** with both terminal endpoints.
- If the path request fails, it retries using best effort and records only the best-effort result in the database.

# Timeouts:
- Defined in the configuration file (e.g., if set to **20 minutes**, creation, validation, and resource activation must complete within this timeframe).
- Similar constraints apply to cancellation requests.

# Path Creation Scenarios and Workflow (Step by Step):

## **CREATE: Successful and Validated, CANCEL: Successful and Validated**
- Log information inside database.
- Remove request from **SENSE-O**.

## **In any of CREATE/CANCEL: Successfully Accepted but Validation Failed**
- Log information inside database.
- The entry remains in **SENSE-O** for debugging.
- The endpoint pair is excluded from future tests until manually deleted.

## **Any Other Failures**
- **If failure is due to "Failed to find path":**  
  - Log information inside database.  
  - Remove request from **SENSE-O**, and the pair is retested in the next cycle.
- **If path creation fails due to other reasons** (e.g., timeout, RM no reply, any other exception):  
  - Log information inside database.  
  - The entry remains in **SENSE-O** for debugging.  
  - The pair is not tested again until deleted from **SENSE-O**.

# Testing Restrictions:
- As long as an endpoint pair exists in **SENSE-O** and was created by `EndToEndTester`, it is excluded from future tests.
