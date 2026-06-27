from locust import HttpUser, task, between

class StudentUser(HttpUser):
    wait_time = between(1, 3)

    @task(5)
    def get_complaints(self):
        self.client.get("/complaints")

    @task(3)
    def get_stats(self):
        self.client.get("/stats")

    @task(2)
    def get_categories(self):
        self.client.get("/categories")

    @task(2)
    def get_leaderboard(self):
        self.client.get("/analytics/leaderboard")

    @task(1)
    def get_heatmap(self):
        self.client.get("/analytics/heatmap")

    @task(1)
    def get_campus_health(self):
        self.client.get("/analytics/campus-health")