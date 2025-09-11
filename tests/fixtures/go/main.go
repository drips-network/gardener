package main

import (
    "fmt"
    "os"
    "net/http"
    "strings"
)

import "github.com/gin-gonic/gin"
import "github.com/spf13/cobra"
import log "github.com/sirupsen/logrus"
import . "github.com/smartystreets/goconvey/convey" // Dot import
import _ "github.com/lib/pq"                       // Blank import for side effects

import "./utils"
import "./config" // Changed from ../config to ./config
// import "archive/zip" // Commented-out import
import "io/ioutil" // File reading

func main() {
    fmt.Println("Main function")
    _, _ = http.Get("http://example.com")
    _ = strings.ToUpper("hello")
    _ = os.Getenv("USER")

    router := gin.Default()
    router.GET("/ping", func(c *gin.Context) {
        c.JSON(200, gin.H{
            "message": "pong",
        })
    })

    var rootCmd = &cobra.Command{Use: "app"}
    rootCmd.Execute()

    log.Info("Logging with aliased import")

    // Convey("Example test", func() { // Example usage of dot import
    //  So(1, ShouldEqual, 1)
    // })

    // Example usage of local packages
    utils.HelperFunc()
    // config.LoadConfig() // This would be from ../config if it were a real import

    data, _ := ioutil.ReadFile("go.mod") // Example of using an import with a trailing comment
    fmt.Println(string(data))

    // Example of an import inside a function (less common)
    initApp()
}

func initApp() {
    // import "path/filepath" // This is not standard Go practice for imports
    // fmt.Println(filepath.Abs("."))
    fmt.Println("initApp called")
}