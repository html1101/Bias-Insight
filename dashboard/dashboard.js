const ctx = document.getElementById('big-chart');
const EPSILON = 0.01;

// Convert seconds of viewing time to minutes
const sToTime = (s) => {
    return Math.round(s/60*100)/100;
}

const labels = {
    "emotions": ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"],
    "stereotype_score": ["unrelated", "stereotype_gender", "stereotype_race", "stereotype_profession", "stereotype_religion"],
    "political_labels": ["left", "center", "right"]
}

const colors = {
    anger: "#f36c66",
    disgust: "#b1d6a2",
    fear: "#f6c2a2",
    joy: "#bb8dc3",
    sadness: "#74a5c2",
    neutral: "#9f9f9f",
    surprise: "#f8fab2",
    
    right: "#e48186",
    center: "#b3b3b3",
    left: "#b1bee7",
    
    women: "#d187f2",
    gender: "#fef8cb",
    profession: "#8da9b6",
    race: "#8ed8ff",
    unrelated: "#9f9f9f",
    religion: "#bee0b0"
};

const getDate = () => {
    const dateObj = new Date();
    const month   = dateObj.getUTCMonth() + 1; // months from 1-12
    const day     = dateObj.getUTCDate();
    const year    = dateObj.getUTCFullYear();

    // Using padded values, so that 2023/1/7 becomes 2023/01/07
    const pMonth        = month.toString().padStart(2,"0");
    const pDay          = day.toString().padStart(2,"0");
    const newPaddedDate = `${pDay}-${pMonth}-${year.toString().padStart(4, "0")}`;
    return newPaddedDate;
}

const fillBigChart = async (category = "emotions") => {
    const points = new Array(25).fill(0).map((_, i) => i);
    console.log("Got date: ", getDate());
    const fetchDay = points.map((_, i) => `${getDate()} (${i.toString().padStart(2, "0")})`);
    let data = {};
    for(let point of fetchDay) {
        // Make request for each from backend + populate
        // We could do this multithreaded, but FastAPI doesn't support it :(
        const info = await fetch(`http://localhost:8000/day_stats?day=${point}`).then(e => e.json());
        if(info[category]) {
            console.log("Got info: ", info[category]);
            // Go through each category in the emotions + add them to data
            for(category_attr in info[category]) {
                if(category_attr in data)
                    data[category_attr].push(info[category][category_attr]*sToTime(info.viewing_time));
                else data[category_attr] = [
                    info[category][category_attr]*sToTime(info.viewing_time)
                ];
            }
        } else {
            for(let attr of labels[category]) {
                if(attr in data) data[attr].push(0)
                else data[attr] = [0]
            }
        }
    }
    // Now set up data so that it is in the format Chart expects
    const formattedData = [];
    for(let pointLabel of Object.keys(data)) {
        formattedData.push({
            label: pointLabel,
            data: data[pointLabel],
            backgroundColor: colors[pointLabel]// + "55",
            // borderColor: colors[pointLabel]
        });
    }

    console.log("Plotting data: ", formattedData);
    // Large chart:
    new Chart(ctx, {
    type: 'bar',
    data: {
        labels: points,
        datasets: formattedData
    },
    options: {
        /*elements: {
            bar: {
                borderWidth: 2
            }
        },*/
        scales: {
            x: {
                stacked: true,
                title: {
                    display: true,
                    text: 'Hours'
                },
                ticks: {
                    // Include the time in the ticks
                    callback: function(value, index, ticks) {
                        return value.toString().padStart(2, "0") + ":00";
                    }
                }
            },
            y: {
                beginAtZero: true,
                stacked: true,
                title: {
                    display: true,
                    text: 'Time Spent (min)'
                }
            }
        }
    }
    });
}

const fillTodayStatus = async () => {
    // Get today's information + display in a radar chart
    const info = (await fetch(`http://localhost:8000/today`).then(e => e.json())).emotions;
    // Add each point to 
    
    const todayChart = document.getElementById("today-chart");

    // Remove neutral element because it's always so high
    // it's impossible to see anything else
    delete info["neutral"];
    const toLog = Object.values(info).map(e =>
        Math.log(Math.max(e, EPSILON)));
    const largest = Math.max(...toLog) - Math.min(...toLog);
    // Large chart:
    new Chart(todayChart, {
        type: 'radar',
        data: {
            labels: Object.keys(info),
            datasets: [{
                label: "Emotions",
                data: toLog.map(e => (e - Math.min(...toLog)) / largest),
                fill: true,
                backgroundColor: 'rgba(255, 99, 132, 0.2)',
                borderColor: 'rgb(255, 99, 132)',
                pointBackgroundColor: 'rgb(255, 99, 132)',
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: 'rgb(255, 99, 132)'
            }]
        },
        options: {
            elements: {
            line: {
                borderWidth: 3
            }
            }
        }
    });
}

const fillTopWords = async () => {
    const bow = await fetch("http://localhost:8000/get_bow").then(e => e.json());
    const total = bow.reduce((a, b) => a + b[1], 0);
    console.log("Total: ", total);
    const wordElem = document.querySelector(".top-words");

    // Go through each word and render it
    const bowSort = bow.sort(e => e[1]);
    for(let wordPop of bowSort) {
        const word = document.createElement("div");
        word.className = "word";
        word.innerHTML = `<b>${wordPop[0]}</b><br/>Top ${100 - Math.round(wordPop[1] * 100 / total)}% searched term`

        wordElem.appendChild(word);
    }
}

const fillInsights = async () => {
    // Fetch information about insights
    const insights = await fetch("http://localhost:8000/overall_results").then(e => e.json());
    
    const { total_viewing_time, weighted_scores } = insights;

    // (1) Find top negative vs positive
    const { emotions, political_bias } = weighted_scores;
    const neg = (["anger", "disgust", "fear"].map(e => emotions[e])).reduce((a, b) => a+b);
    const pos = (["joy", "sadness", "surprise"].map(e => emotions[e])).reduce((a, b) => a+b);
    const total = emotions.neutral + neg + pos;

    const negElem = document.querySelector(".insights .negative");
    negElem.querySelector(".percent").innerHTML = Math.round((neg > pos ? neg : pos) * 100 / total) + "%";
    negElem.querySelector("u").innerHTML = neg > pos ? "negative" : "positive";

    const timeElem = document.querySelector(".time-browsing");
    timeElem.querySelector(".percent").innerHTML = total_viewing_time < 60 ?
        total_viewing_time + "s" : total_viewing_time / 60 < 60 ? Math.round(total_viewing_time/60 * 100)/100 + "min" : 
        Math.round(total_viewing_time/60/60 * 100)/100 + "hr";

    const { left, center, right } = political_bias;
    const totalPol = left + center + right;
    const politicalElem = document.querySelector(".insights .political");
    const bestVal = left > center && left > right ? "left-leaning" :
        right > center ? "right-leaning" : "centrist";
    politicalElem.querySelector(".percent").innerHTML = Math.round(Math.max(left, center, right) * 100 / totalPol) + "%";
    politicalElem.querySelector("u").innerHTML = bestVal;
}

// Fill chart with information from list
fillBigChart();

// Fill chart with today's status
fillTodayStatus();

// Fill with top 75 words
fillTopWords();

// Fill insights with information about overall content consumed
fillInsights();