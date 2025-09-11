package api

import "net/http"

// FetchData simulates fetching data from an API
func FetchData(url string) (*http.Response, error) {
    resp, err := http.Get(url)
    if err != nil {
        return nil, err
    }
    return resp, nil
}