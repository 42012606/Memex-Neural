const { createApp, ref, onMounted, nextTick } = Vue;

const app = createApp({
    setup() {
        // State
        const stats = ref({
            summary: {
                total_archives: 0,
                vector_coverage: 0,
                pending_proposals: 0
            },
            charts: {
                activity_30d: { labels: [], data: [] },
                type_distribution: { labels: [], data: [] }
            }
        });
        const proposals = ref([]);
        const loading = ref(true);
        const currentUser = ref(null);

        // --- Navigation ---
        const isSidebarOpen = ref(false);
        const toggleSidebar = () => {
            isSidebarOpen.value = !isSidebarOpen.value;
        };

        const goHome = () => {
            window.location.href = '/';
        };

        const logout = () => {
            localStorage.removeItem('memex_token');
            window.location.href = '/';
        };

        // --- API Calls ---
        const fetchStats = async () => {
            try {
                const token = localStorage.getItem('memex_token');
                if (!token) throw new Error("No token provided");

                const response = await axios.get('/api/v1/dashboard/stats', {
                    headers: { Authorization: `Bearer ${token}` }
                });
                stats.value = response.data;
                renderCharts();
            } catch (error) {
                console.error("Failed to fetch stats:", error);
                if (error.response && error.response.status === 401) {
                    logout();
                }
            }
        };

        const fetchProposals = async () => {
            try {
                const token = localStorage.getItem('memex_token');
                if (!token) return;

                const response = await axios.get('/api/v1/dashboard/proposals', {
                    headers: { Authorization: `Bearer ${token}` }
                });
                proposals.value = response.data;
            } catch (error) {
                console.error("Failed to fetch proposals:", error);
            }
        };

        const fetchUser = async () => {
            try {
                const token = localStorage.getItem('memex_token');
                if (!token) {
                    window.location.href = '/'; // Must login first
                    return;
                }
                const response = await axios.get('/api/v1/auth/me', {
                    headers: { Authorization: `Bearer ${token}` }
                });
                currentUser.value = response.data;
            } catch (error) {
                console.error("Auth check failed:", error);
                logout();
            }
        };

        // --- Actions ---
        const approveProposal = async (id) => {
            if (!confirm("确定要批准此提案吗？")) return;
            try {
                const token = localStorage.getItem('memex_token');
                await axios.post(`/api/v1/proposals/${id}/approve`, {}, {
                    headers: { Authorization: `Bearer ${token}` }
                });
                // Optimistic UI update
                proposals.value = proposals.value.filter(p => p.id !== id);
                await fetchStats(); // Refresh stats to show new vector nodes
            } catch (error) {
                console.error("Approve failed:", error);
                alert("批准失败: " + (error.response?.data?.detail || error.message));
            }
        };

        const rejectProposal = async (id) => {
            if (!confirm("确定要拒绝此提案吗？")) return;
            try {
                const token = localStorage.getItem('memex_token');
                if (!token) return;

                await axios.post(`/api/v1/proposals/${id}/reject`, {}, {
                    headers: { Authorization: `Bearer ${token}` }
                });

                proposals.value = proposals.value.filter(p => p.id !== id);
                await fetchStats();
            } catch (error) {
                console.error("Reject failed:", error);
                alert("拒绝失败: " + (error.response?.data?.detail || error.message));
            }
        };
        // --- Charts ---
        let activityChart = null;
        let typeChart = null;

        const renderCharts = async () => {
            await nextTick(); // Wait for DOM update

            // 1. Activity Line Chart
            const activityCtx = document.getElementById('activityChart');
            if (activityCtx) {
                if (activityChart) activityChart.destroy();
                activityChart = new Chart(activityCtx, {
                    type: 'line',
                    data: {
                        labels: stats.value.charts.activity_30d.labels,
                        datasets: [{
                            label: '新增归档',
                            data: stats.value.charts.activity_30d.data,
                            borderColor: '#8b5cf6', // Violet
                            backgroundColor: 'rgba(139, 92, 246, 0.1)',
                            tension: 0.4,
                            fill: true
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            y: { beginAtZero: true, grid: { color: '#333' } },
                            x: { grid: { display: false } }
                        }
                    }
                });
            }

            // 2. Type Doughnut Chart
            const typeCtx = document.getElementById('typeChart');
            if (typeCtx) {
                if (typeChart) typeChart.destroy();
                typeChart = new Chart(typeCtx, {
                    type: 'doughnut',
                    data: {
                        labels: stats.value.charts.type_distribution.labels,
                        datasets: [{
                            data: stats.value.charts.type_distribution.data,
                            backgroundColor: [
                                '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6'
                            ],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'right', labels: { color: '#ccc' } }
                        }
                    }
                });
            }
        };

        onMounted(async () => {
            await fetchUser();
            await fetchStats();
            await fetchProposals();
            loading.value = false;
        });

        return {
            stats,
            proposals,
            loading,
            currentUser,
            isSidebarOpen,
            toggleSidebar,
            goHome,
            logout,
            approveProposal,
            rejectProposal
        };
    }
});

app.mount('#app');
