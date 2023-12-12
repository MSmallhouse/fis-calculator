const lambdaURL = "https://imvf3e6jot4nih4i5th43endj40jbfqa.lambda-url.us-east-2.on.aws/";

const url = document.getElementById("urlInput");
const submitResponse = document.getElementById("response");
const form = document.getElementById("userInfo");
form.setAttribute("action", lambdaURL);
form.setAttribute("method", "get");

form.onsubmit = e => {
    e.preventDefault();

    let points = fetch(`${lambdaURL}?url=${encodeURIComponent(url.value)}`)

    points.then(response => response.json())
        .then(data => {
            // handle response from Lambda function
            console.log(data);
        })
        .catch(error => {
            console.log("Error: ", error);
        });
}