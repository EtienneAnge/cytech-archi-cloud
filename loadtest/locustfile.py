"""Load tests for the base converter.

Target host is set with --host (or LOCUST_HOST), so the same file works
against local node, a Docker container, or a Kubernetes Service/Ingress.

Scenarios:
  - ConverterUser : realistic traffic (mixed endpoints, think time)
  - StressUser    : CPU-bound traffic on /heavy, used to trigger the HPA

/heavy blocks the Node event loop (~50-100 ms per call) so every other
request on the same pod waits behind it. To keep the mixed run meaningful:
  - StressUser is weighted 1 vs 10 for ConverterUser and has a short think time
    (with wait_time=0 a few users saturate the pod and everything times out);
  - every request has an explicit timeout and is validated, so a slow or
    dropped /heavy shows up as a failure instead of hanging the user.
Run only the stress scenario with:  locust -f locustfile.py StressUser
"""
import random

from locust import HttpUser, between, task


def random_case():
    n = random.randint(0, 2**64)
    base = random.choice(["bin", "dec", "hex"])
    value = {"bin": f"{n:b}", "dec": str(n), "hex": f"{n:X}"}[base]
    to = random.choice([b for b in ("bin", "dec", "hex") if b != base])
    return {"value": value, "from": base, "to": to}


# Seconds before a request is counted as failed (connect, read)
TIMEOUT = (5, 30)


def check_json(r, key):
    """Mark the response failed unless it is HTTP 200 with JSON containing `key`."""
    if r.status_code != 200:
        r.failure(f"HTTP {r.status_code}" if r.status_code else f"no response: {r.error}")
        return
    try:
        if r.json().get(key) is None:
            r.failure(f"missing {key}")
    except ValueError:
        r.failure("invalid JSON")


class ConverterUser(HttpUser):
    weight = 10
    wait_time = between(0.5, 2)

    @task(1)
    def home_page(self):
        self.client.get("/", name="GET /", timeout=TIMEOUT)

    @task(8)
    def convert(self):
        case = random_case()
        with self.client.post("/api/convert", json=case, name="POST /api/convert",
                              timeout=TIMEOUT, catch_response=True) as r:
            check_json(r, "result")

    @task(1)
    def invalid_input(self):
        # Error path: the server must answer 400, not crash
        with self.client.post("/api/convert", json={"value": "12", "from": "bin", "to": "dec"},
                              name="POST /api/convert [invalid]", timeout=TIMEOUT,
                              catch_response=True) as r:
            if r.status_code == 400:
                r.success()
            else:
                r.failure(f"expected 400, got {r.status_code}")


class StressUser(HttpUser):
    weight = 1
    wait_time = between(0.1, 0.5)   # near-continuous pressure without starving the pod

    @task
    def heavy(self):
        with self.client.get("/heavy", name="GET /heavy",
                             timeout=TIMEOUT, catch_response=True) as r:
            check_json(r, "result")
