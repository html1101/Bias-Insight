console.log("This is the service worker");

chrome.runtime.onMessage.addListener(async (message, sender, sendResponse) => {
    if (message.action === "message") {
        // Store the resulting message in our database:
        // Add to object of websites we already have saved
        let websites = (await chrome.storage.local.get(["websites"])).websites ?? {};
        console.log("Got existing websites: ", websites);
        websites[message.website] = message.data;
        chrome.storage.local.set({ websites });
        console.log("Got message data: ", message);
    }
});
