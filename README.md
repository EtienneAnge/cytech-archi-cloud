# Base Converter — Déploiement Kubernetes sur GKE

> **CY Tech — ING3 ICC — Cloud Infrastructures (2026–2027)**
> Projet noté — **Assignment Brief 6 : Container Orchestration with Kubernetes (GKE)**

Application web **Node.js / Express** de conversion de bases (binaire ↔ décimal ↔ hexadécimal), conteneurisée avec Docker et déployée sur un cluster **Google Kubernetes Engine**, avec exposition publique via un **LoadBalancer** et **autoscaling horizontal (HPA)**.



## 1. Architecture

chart de este

- Le **load balancer** répartit les connexions entre les nœuds, puis **kube-proxy** les redirige vers un pod `Ready` (éventuellement sur l'autre nœud).
- Le client ne voit que le **port 80** ; la traduction vers le port **3000** de l'application est faite par le Service (`port: 80` → `targetPort: 3000`).
- L'application est **stateless** : n'importe quel pod peut traiter n'importe quelle requête, ce qui la rend idéale pour le scaling horizontal.

---

## 3. Structure du dépôt

```
webApp/
├── Dockerfile
├── locustfile.py        
├── k8s/
│   ├── deployment.yaml    
│   ├── service.yaml       
│   └── hpa.yaml           

```

---

## 4. Déploiement

### 4.1 Conteneurisation et publication de l'image

```bash
docker build -t etienneange/base-converter:latest .
docker push etienneange/base-converter:latest
```

### 4.2 Création du cluster GKE

```bash
gcloud config set project <PROJECT_ID>
gcloud services enable container.googleapis.com

gcloud container clusters create base-converter-cluster \
  --zone europe-west9-a \
  --num-nodes 2 \
  --machine-type e2-medium \
  --disk-type pd-standard \
  --disk-size 30 \
  --enable-autoscaling --min-nodes 1 --max-nodes 3

gcloud container clusters get-credentials base-converter-cluster --zone europe-west9-a
kubectl get nodes        # 2 nœuds Ready
```

**Choix justifiés (Resource management)** : cluster **zonal** (et non régional, qui triplerait le nombre de nœuds), machines `e2-medium` de petite taille, disques `pd-standard` moins coûteux que le SSD, et plafond de 3 nœuds pour borner les coûts.

### 4.3 Déploiement des manifests

```bash
kubectl apply -f k8s/
kubectl get pods                             
kubectl get svc base-converter-service       
```

Extrait du `deployment.yaml` (conteneur) :

```yaml
containers:
  - name: base-converter
    image: etienneange/base-converter:latest
    ports:
      - containerPort: 3000
    readinessProbe:
      httpGet: { path: /ready, port: 3000 }
      initialDelaySeconds: 5
      periodSeconds: 5
      failureThreshold: 2
    livenessProbe:
      httpGet: { path: /live, port: 3000 }
      initialDelaySeconds: 15
      periodSeconds: 10
      failureThreshold: 3
```

Extrait du `service.yaml` :

```yaml
spec:
  type: LoadBalancer
  selector:
    app: base-converter
  ports:
    - port: 80          # port public
      targetPort: 3000  # port de l'application dans le conteneur
```

L'application est alors accessible sur **`http://<EXTERNAL-IP>`**.

---

## 5. Scaling

### 5.1 Scaling manuel

```bash
kubectl scale deployment base-converter-deployment --replicas=5
kubectl get pods -o wide     # répartition des pods sur les 2 nœuds
```

### 5.2 Autoscaling automatique (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: base-converter
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: base-converter-deployment
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 75
```

Le pourcentage est calculé **par rapport à `requests.cpu`** du conteneur (et non à la `limit`), en **moyenne sur tous les pods**. Quand la moyenne dépasse le seuil, le HPA ajoute des pods ; si les nœuds manquent de place, le **Cluster Autoscaler** ajoute un nœud.

```bash
kubectl apply -f k8s/hpa.yaml
kubectl get hpa -w
```

Comme une conversion de base est quasi instantanée et ne sollicite presque pas le CPU, une route **`/heavy`** (boucle de calcul) a été ajoutée pour **simuler une charge CPU réaliste** et déclencher l'autoscaling.

---

## 6. Tests de charge et analyse des logs

Les tests sont réalisés avec **Locust** depuis un poste local : le trafic passe ainsi par Internet et par le load balancer, comme pour un vrai utilisateur, sans consommer le CPU des nœuds du cluster.

```bash
locust -f locustfile.py --host http://<EXTERNAL-IP> StressUser
```

> ⚠️ `--host` doit contenir l'adresse **sans port** (port 80 par défaut, celui du Service). Viser `:3000` échoue, car ce port n'existe qu'à l'intérieur du cluster.

Les logs de tous les pods sont récupérés avec le sélecteur de label ; l'option `--prefix` affiche le nom du pod qui a traité chaque requête :

```bash
kubectl logs -l app=base-converter --prefix -f
```

### 6.1 Sans autoscaling — état au repos

```bash
kubectl logs -l app=base-converter --prefix -f
```

```
[pod/base-converter-deployment-7678d4fb47-zjdjc/base-converter] 2026-10-13T12:55:03.583Z GET /ready
[pod/base-converter-deployment-7678d4fb47-zpxq7/base-converter] 2026-10-13T12:55:06.631Z GET /ready
[pod/base-converter-deployment-7678d4fb47-zjdjc/base-converter] 2026-10-13T12:55:08.464Z GET /live
[pod/base-converter-deployment-7678d4fb47-zjdjc/base-converter] 2026-10-13T12:55:08.582Z GET /ready
[pod/base-converter-deployment-7678d4fb47-zpxq7/base-converter] 2026-10-13T12:55:11.621Z GET /ready
[pod/base-converter-deployment-7678d4fb47-zjdjc/base-converter] 2026-10-13T12:55:13.583Z GET /ready
[pod/base-converter-deployment-7678d4fb47-zpxq7/base-converter] 2026-10-13T12:55:16.621Z GET /ready
```

**Analyse :**

- **2 pods** seulement sont actifs (`zjdjc` et `zpxq7`), ce qui correspond à `replicas: 2` / `minReplicas: 2`.
- Les seules requêtes visibles sont les **health checks Kubernetes** :
  - `GET /ready` toutes les **5 s** par pod (`readinessProbe`, `periodSeconds: 5`) ;
  - `GET /live` toutes les **10 s** (`livenessProbe`, `periodSeconds: 10`).
- Les deux pods répondent correctement aux probes : ils sont `Ready` et reçoivent le trafic du Service.

![Charts avant l'autoscaling](docs/rapport/number_of_users_1791902715.959.png)

### 6.2 Avec autoscaling — sous charge (`/heavy`)

```bash
kubectl logs -l app=base-converter --prefix
```

Extrait représentatif (log complet ci-dessous) :

```
[pod/base-converter-deployment-d7676b595-zmj59/base-converter] Converter running on http://localhost:3000
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:05.407Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:05.015Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:05.493Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:05.976Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:06.679Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:05.735Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] Converter running on http://localhost:3000
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:02.657Z GET /ready
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:07.609Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:07.001Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:05.384Z GET /heavy
```

**Répartition des requêtes par pod** (fenêtre 15:02:05 → 15:02:10) :

| Pod | Requêtes `/heavy` affichées | Remarque |
|---|:---:|---|
| `5qd7z` | 10 | traite la charge |
| `8dhmf` | 10 | traite la charge |
| `bvqhq` | 10 | traite la charge |
| `c7zg7` | 10 | traite la charge |
| `fgtb8` | 10 | traite la charge |
| `jdcvk` | 10 | traite la charge |
| `lwplz` | 10 | traite la charge |
| `r6vcb` | 10 | traite la charge |
| `k2vjl` | 7 | **pod tout juste créé** : démarrage → `/ready` à 15:02:02 → première requête `/heavy` à 15:02:07 |
| `zmj59` | 0 | **pod en cours de démarrage** : pas encore `Ready`, donc aucun trafic reçu |

**Analyse :**

1. **L'autoscaling a fonctionné** : on passe de **2 pods** au repos à **10 pods** sous charge, soit le `maxReplicas: 10` du HPA. La charge CPU générée par `/heavy` a dépassé le seuil, et le HPA a ajouté des replicas.
2. **Le load balancing fonctionne** : les requêtes sont réparties sur **tous les pods prêts**, et chacun traite des requêtes `/heavy` sur la même période.
3. **Rôle de la readiness probe** : le pod `k2vjl` démarre, valide sa probe `/ready`, puis reçoit immédiatement du trafic. Le pod `zmj59`, encore en démarrage, n'en reçoit pas. Kubernetes n'envoie le trafic qu'aux pods prêts, il n'y a donc **aucune erreur pendant le scale-up**.
4. **Remarque méthodologique** : avec un sélecteur (`-l`), `kubectl logs` n'affiche par défaut que les **10 dernières lignes par pod**. Le nombre de 10 requêtes par pod est donc une limite d'affichage, pas un comptage exact. L'information pertinente est que **tous les pods** reçoivent du trafic simultanément.

![Charts après l'autoscaling](docs/rapport/number_of_users_1791910731.087.png)

<details>
<summary><b>Logs complets avec autoscaling</b></summary>

```
[pod/base-converter-deployment-d7676b595-zmj59/base-converter] Converter running on http://localhost:3000
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:05.407Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:05.687Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:05.957Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:06.603Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:06.902Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:07.619Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:07.931Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:08.204Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:09.493Z GET /heavy
[pod/base-converter-deployment-d7676b595-5qd7z/base-converter] 2026-10-13T15:02:09.696Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:05.015Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:05.237Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:05.748Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:06.030Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:06.831Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:07.317Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:08.299Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:08.524Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:09.234Z GET /heavy
[pod/base-converter-deployment-d7676b595-8dhmf/base-converter] 2026-10-13T15:02:09.509Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:05.493Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:06.007Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:06.346Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:07.089Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:07.864Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:08.301Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:08.563Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:08.844Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:09.054Z GET /heavy
[pod/base-converter-deployment-d7676b595-bvqhq/base-converter] 2026-10-13T15:02:09.847Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:05.976Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:06.237Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:06.505Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:07.230Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:07.518Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:07.790Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:08.238Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:09.227Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:09.503Z GET /heavy
[pod/base-converter-deployment-d7676b595-c7zg7/base-converter] 2026-10-13T15:02:09.760Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:06.679Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:06.913Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:07.197Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:07.395Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:08.172Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:08.447Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:08.686Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:08.890Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:09.483Z GET /heavy
[pod/base-converter-deployment-d7676b595-fgtb8/base-converter] 2026-10-13T15:02:09.680Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:05.735Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:06.433Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:06.849Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:07.156Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:07.441Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:07.647Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:08.128Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:08.644Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:09.634Z GET /heavy
[pod/base-converter-deployment-d7676b595-jdcvk/base-converter] 2026-10-13T15:02:09.876Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] Converter running on http://localhost:3000
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:02.657Z GET /ready
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:07.609Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:08.386Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:08.962Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:09.161Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:09.663Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:09.876Z GET /heavy
[pod/base-converter-deployment-d7676b595-k2vjl/base-converter] 2026-10-13T15:02:10.621Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:07.001Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:07.625Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:08.013Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:08.342Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:08.597Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:08.837Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:09.081Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:09.332Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:09.587Z GET /heavy
[pod/base-converter-deployment-d7676b595-lwplz/base-converter] 2026-10-13T15:02:09.976Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:05.384Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:05.591Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:05.846Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:06.605Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:07.019Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:07.327Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:07.684Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:09.513Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:10.483Z GET /heavy
[pod/base-converter-deployment-d7676b595-r6vcb/base-converter] 2026-10-13T15:02:10.763Z GET /heavy
```

</details>

---

## 7. Nettoyage des ressources

Le cluster et le load balancer sont facturés en continu. Ils sont supprimés une fois la notation terminée :

```bash
kubectl delete -f k8s/          # supprime aussi le load balancer et son IP publique
gcloud container clusters delete base-converter-cluster --zone europe-west9-a
```