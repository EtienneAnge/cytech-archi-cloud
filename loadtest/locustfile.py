"""Load tests for the base converter.

Target host is set with --host (or LOCUST_HOST), so the same file works
against local node, a Docker container, or a Kubernetes Service/Ingress.

Scenarios:
  - ConverterUser : realistic traffic (mixed endpoints, think time)
  - StressUser    : CPU-bound traffic on /heavy, used to trigger the HPA
"""
import random

from locust import HttpUser, between, constant, task


def random_case():
    n = random.randint(0, 2**64)
    base = random.choice(["bin", "dec", "hex"])
    value = {"bin": f"{n:b}", "dec": str(n), "hex": f"{n:X}"}[base]
    to = random.choice([b for b in ("bin", "dec", "hex") if b != base])
    return {"value": value, "from": base, "to": to}


class ConverterUser(HttpUser):
    wait_time = between(0.5, 2)

    @task(1)
    def home_page(self):
        self.client.get("/", name="GET /")

    @task(8)
    def convert(self):
        case = random_case()
        with self.client.post("/api/convert", json=case, name="POST /api/convert",
                              catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
            elif not r.json().get("result"):
                r.failure("missing result")

    @task(1)
    def invalid_input(self):
        # Error path: the server must answer 400, not crash
        with self.client.post("/api/convert", json={"value": "12", "from": "bin", "to": "dec"},
                              name="POST /api/convert [invalid]", catch_response=True) as r:
            if r.status_code == 400:
                r.success()
            else:
                r.failure(f"expected 400, got {r.status_code}")


class StressUser(HttpUser):
    wait_time = constant(0)   # no think time: maximum pressure

    @task
    def heavy(self):
        self.client.get("/heavy", name="GET /heavy")