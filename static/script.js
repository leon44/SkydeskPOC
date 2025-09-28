let weatherChart = null;

document.getElementById('submit-btn').addEventListener('click', () => {
    const query = document.getElementById('query-input').value;
    const resultElement = document.getElementById('result');
    const chartContainer = document.getElementById('chart-container');
    const summaryContainer = document.getElementById('summary-container');

    resultElement.textContent = 'Processing...';
    chartContainer.style.display = 'none';
    summaryContainer.style.display = 'none';

    if (weatherChart) {
        weatherChart.destroy();
    }

    fetch('/process_request', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query: query }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            resultElement.textContent = `Error: ${data.error}`;
        } else {
            // Populate summary
            summaryContainer.textContent = data.llm_summary;
            summaryContainer.style.display = 'block';

            // Display raw JSON
            resultElement.textContent = JSON.stringify(data.weather_data, null, 2);
            
            // Render chart
            chartContainer.style.display = 'block';
            renderWeatherChart(data.weather_data);
        }
    })
    .catch(error => {
        resultElement.textContent = `Error: ${error}`;
    });
});

function renderWeatherChart(weatherData) {
    const ctx = document.getElementById('weather-chart').getContext('2d');
    if (!weatherData.features || !weatherData.features[0] || !weatherData.features[0].properties) {
        console.error('Data is not in the expected format:', weatherData);
        return;
    }
    const properties = weatherData.features[0].properties;
    const timestamps = Object.keys(properties);
    if (timestamps.length === 0) {
        console.error('No observation data to render.');
        return;
    }
    const labels = timestamps.map(ts => new Date(ts).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }));
    const parameters = Object.keys(properties[timestamps[0]]);
    const chartColors = ['rgb(75, 192, 192)', 'rgb(255, 99, 132)', 'rgb(54, 162, 235)', 'rgb(255, 206, 86)', 'rgb(153, 102, 255)'];
    const datasets = parameters.map((param, index) => ({
        label: param,
        data: timestamps.map(ts => properties[ts][param]),
        borderColor: chartColors[index % chartColors.length],
        tension: 0.1,
        yAxisID: param
    }));
    weatherChart = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                ...parameters.reduce((axes, param, index) => {
                    axes[param] = {
                        type: 'linear',
                        display: true,
                        position: index % 2 === 0 ? 'left' : 'right',
                        grid: { drawOnChartArea: index === 0 },
                        ticks: { color: chartColors[index % chartColors.length] }
                    };
                    return axes;
                }, {})
            }
        }
    });
}