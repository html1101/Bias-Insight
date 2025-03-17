// By default, show bias insight for specific website
let useSpecificWebsite = true;

const renderSliderGivenElem = (slider, data) => {
  // Sort keys according to their significance
  for (let attr of Object.keys(data)) {
    slider.querySelector(`.${attr}`).setAttribute("style", `width:${data[attr] * 100}%`);
    if (data[attr] < 0.15) {
      // If the emotion isn't large enough, don't show text
      slider.querySelector(`.${attr}`).innerHTML = "";
    }
  }
}

const renderSliders = (data) => {
  // (1) Emotion sliders
  const emotionSlider = document.querySelector(".emotion-slider");
  renderSliderGivenElem(emotionSlider, data.emotions);

  // (2) Political bias
  const politicalSlider = document.querySelector(".politics-slider");
  renderSliderGivenElem(politicalSlider, data.political_bias);

  // (3) Stereotype
  const stereotypeSlider = document.querySelector(".stereotype-slider");
  // Get points to add up to 1
  const stereo = data.stereotype;
  const total = (Object.keys(stereo).map(e => stereo[e]).reduce((a, b) => a + b));
  let newStereo = data.stereotype;
  for (let key of Object.keys(newStereo)) {
    newStereo[key] /= total;
  }
  renderSliderGivenElem(stereotypeSlider, newStereo);

  // (3) Negative/positive
  // Fill "content is mostly ..."
  const { anger, disgust, fear, joy, sadness, neutral, surprise } = data.emotions;
  // Add up all of the good things
  const goodNews = surprise + joy;
  const badNews = anger + disgust + fear + sadness;
  // If bad
  const negPosElem = document.querySelector(".content");
  if (badNews > 0.3 && goodNews < 0.3) {
    negPosElem.innerHTML = "NEGATIVE";
  } else if (goodNews > 0.3 && badNews < 0.3) {
    negPosElem.innerHTML = "POSITIVE";
  } else {
    negPosElem.innerHTML = "NEUTRAL";
  }

  /*const negPos = data.sentiment_score;
  const intensity = document.querySelector(".intensity");
  const negPosElem = document.querySelector(".content");
  if(Math.abs(negPos) < 0.9) {
    intensity.innerHTML = "";
  }
  else if(Math.abs(negPos) < 0.9) {
    intensity.innerHTML = "moderately";
  }
  else {
    intensity.innerHTML = "mostly";
  }
  console.log("Intensity: ", negPos);
  negPosElem.innerHTML = Math.abs(negPos) < 0.9 ? "NEUTRAL" : 
    negPos < -0.9 ? "NEGATIVE" : "POSITIVE";*/
}

async function renderStats(useWebsite) {
  // Show the website being read
  const webElem = document.querySelector(".website");
  const loading = document.querySelector(".loading");
  loading.setAttribute("style", "display: flex;");

  if (useWebsite) {
    // Use the website we're currently on to get data
    // Show the website being read
    // Send a message to the tab we're currently on (where the content-script is running)
    const [tab] = await chrome.tabs.query({
      active: true, lastFocusedWindow: true
    });
    webElem.innerHTML = (new URL(tab.url)).hostname.replace("www.", "");
    const { data } = await chrome.tabs.sendMessage(tab.id, { render: true });
    renderSliders(data);
  } else {
    webElem.innerHTML = "All Sites";
    // Get the statistics we have within the Chrome extension (TODO)
    const stats = await fetch(`http://localhost:8080/overall_results`).then(res => res.json());
    console.log("Got the stats: ", stats);
    // Now fill the stats
    renderSliders(stats.weighted_scores);
  }
  loading.setAttribute("style", "display: none;");
}

renderStats(useSpecificWebsite);

// Update stats when we switch to a different website
const elem = document.getElementById("switchstats");
const switchStats = () => {
  // Switch around the status + change the switcher's content
  useSpecificWebsite = !useSpecificWebsite;
  elem.innerHTML = `Switch to ${useSpecificWebsite ? "Overall" : "Website"} Stats`;

  // Refresh stats
  renderStats(useSpecificWebsite);
}

elem.addEventListener("click", switchStats);
