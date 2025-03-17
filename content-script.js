/**
 * This is the script that hooks into pages--
 * it takes the content of the page, then analyzes it using the server
 * and stores the resulting information in Chrome storage.
 */

// When we first load the page
// The time we loaded the page in (we update this when page loads)
let startTime = (new Date()).getTime();
// The location we're at
const loc = window.location.hostname;

const getContent = () => {
    return new Promise((res, rej) => {
        // Query for all the content within the page
        const content = (document.body.innerText).split("\n").filter(e => {
            const len = e.split(" ").length;
            return len > 3;
        }).join("\n");

        // Update timestamp right before we request an analysis
        startTime = (new Date()).getTime()/1000;
        // Once we get content, send it off to Makayla's app
        fetch("http://localhost:8080/SMBSanalyze", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                data: content,
                website: loc,
                entry_time: startTime
            })
        }).then(data => data.json()).then(async data => {

            // Send over to the popup script:
            /**
             * 1. The website we're running this from (website)
             * 2. The result of our data analysis (data)
             */
            // const [tab] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
            console.log("Data sending message", data);
            const response = await chrome.runtime.sendMessage({
                action: "message",
                website: window.location.href,
                data
            });
            res(data);
        })
    });
}

window.addEventListener("load", () => {
    // When we first load the page in, 
    startTime = (new Date()).getTime()/1000;
    getContent()
    .then(data => {
        // We got the data!
        // TODO fill frontend with it
    });
})

const leftPage = async () => {
    // Tag the viewing time
    await fetch(`http://localhost:8080/update_viewing_time`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            website: loc,
            exit_time: (new Date()).getTime()/1000
        })
    })
}

window.addEventListener("unload", () => {
    // User just closed out page, update
    leftPage();
});

window.addEventListener("visibilitychange", () => {
    if(document.hidden) {
        // Page has been hidden!
        // Send a request letting the server know we left this page
        leftPage();
    } else {
        getContent()
        .then(data => {
            // We got the data!
            // TODO fill frontend with it
        });
    }
})

chrome.runtime.onMessage.addListener(
    function(request, sender, sendResponse) {
        if(request.render) {
            console.log("Saying we left the page");
            leftPage()
            .then(() => {
                // Once we get a message that we opened the popup,
                // send back the analysis we get from the server
                getContent()
                .then(data => {
                    sendResponse({
                        data,
                        website: loc
                    })
                });
            });
        }
        return true;
    }
);