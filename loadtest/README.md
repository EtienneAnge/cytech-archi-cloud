# Load tests (Locust)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r loadtest/requirements.txt
```

## Web UI
```bash
locust -f loadtest/locustfile.py --host http://localhost:3000
```
Open http://localhost:8089, set users / spawn rate, start.

## Headless (reproducible runs, CSV + HTML report)
```bash
locust -f loadtest/locustfile.py --host http://localhost:3000 \
  --headless -u 100 -r 10 -t 1m \
  --csv loadtest/results/local --html loadtest/results/local.html
```

## Comparing environments
Keep the same `-u -r -t` and change only `--host` and the result name:

| Target      | `--host`                                  | results name |
|-------------|-------------------------------------------|--------------|
| node        | `http://localhost:3000`                   | `local`      |
| Docker      | `http://localhost:3000` (`docker run -p 3000:3000 base-converter`) | `docker` |
| Kubernetes  | Service/Ingress URL, e.g. `http://<node-ip>:<nodePort>` or via `kubectl port-forward svc/<svc> 3000:3000` | `k8s-1replica`, `k8s-3replicas`… |

Note: `kubectl port-forward` goes through a single pod and is a bottleneck;
use a NodePort/LoadBalancer/Ingress to measure real load-balancing across replicas.
