# RightSize — How to Run the Demo

This assumes the cluster, manifests, and Python environment are already set up on your
machine from before. These are just the steps to bring everything up and view the
results each time.

---

## 1. Confirm the cluster is alive

```bash
kubectl get pods -n rightsizing-demo
kubectl get pods -n monitoring
kubectl get pods -n kube-system -l app.kubernetes.io/name=kube-state-metrics
```
**Expect:** every pod `Running`. If any show unusually high `RESTARTS`, that's worth
noting but not necessarily a problem — restart the affected pod with
`kubectl rollout restart deployment <name> -n rightsizing-demo` if its numbers look off
later on.

---

## 2. Start the port-forwards — three separate terminal windows, each left open

**Terminal 1:**
```bash
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

**Terminal 2:**
```bash
kubectl port-forward -n monitoring svc/pushgateway 9091:9091
```

**Terminal 3:**
```bash
kubectl port-forward -n monitoring svc/grafana 3000:3000
```

None of these ever return you to a prompt — that's correct, they're supposed to hang.
Don't close these windows for the rest of the session.

---

## 3. Run the pipeline — a 4th terminal

```bash
cd k8s-rightsizing-advisor/scripts
source venv/bin/activate
python3 main.py
```
(On Windows: `.\venv\Scripts\Activate.ps1` instead of `source venv/bin/activate`.)

**Expect:** a printed table (pod, resource, requested, p90 actual, recommended, waste %,
cost), followed by:
```
Saved to rightsizing_report.csv
Saved to rightsizing_report.json (for the custom dashboard)
Pushed recommendation/waste/cost metrics to Pushgateway (visible in Grafana).
```

---

## 4. Start the custom dashboard's local web server — same Terminal 4

```bash
python3 -m http.server 8080
```
This also hangs — that's expected, leave it running.

---

## 5. What to open in the browser

| What | URL | Shows |
|---|---|---|
| Prometheus | `http://localhost:9090` | Raw PromQL queries |
| Grafana | `http://localhost:3000` | The provisioned 5-panel dashboard |
| Custom dashboard | `http://localhost:8080/dashboard.html` | The hero-figure + resource-ledger view |
| Raw CSV | `cat rightsizing_report.csv` (in Terminal 4) | Plain-text report |

---

## 6. Re-running later, to see fresh numbers

```bash
python3 main.py
```
then refresh the Grafana tab and the custom dashboard tab in your browser. No need to
touch the port-forwards from Section 2.

---

### Quick troubleshooting

- **`ConnectionRefusedError` / page won't load** → the matching port-forward (Section 2)
  isn't running in some terminal.
- **Dashboard or Grafana panels are empty** → `main.py` hasn't been run yet since the
  port-forwards started, or the Pushgateway port-forward specifically isn't up.
- **`(venv)` missing from the prompt** → activate it again; this doesn't persist across
  terminal restarts.
