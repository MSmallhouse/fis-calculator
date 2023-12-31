const lambdaURL = "https://imvf3e6jot4nih4i5th43endj40jbfqa.lambda-url.us-east-2.on.aws/";

const url = document.getElementById("urlInput");
const eventSelector = document.getElementById("eventSelector");
const minPenalty = document.getElementById("minPenalty");
const form = document.getElementById("userInfo");
const results = document.getElementById("results")
form.setAttribute("action", lambdaURL);
form.setAttribute("method", "get");

form.onsubmit = e => {
    e.preventDefault();
    results.innerHTML = "";
    // attach form responses to url as query string
    const requestURL = `${lambdaURL}?url=${encodeURIComponent(url.value)}
                        &min-penalty=${minPenalty.value}
                        &event=${eventSelector.value}`

    fetch(requestURL).then(response => response.json())
        .then(data => {
            console.log(data);
            // handle response from Lambda function
            for (let i=0; i<data.length; i++) {
                const header = document.createElement("h4");
                header.textContent = `${i+1}. ${data[i]}`;
                results.append(header);
            }
        })
        .catch(error => {
            console.log("Error: ", error);
            const header = document.createElement("h4");
            header.textContent = "Something went wrong...";
            document.body.append(header);
        });
}