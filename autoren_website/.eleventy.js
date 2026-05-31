module.exports = function(eleventyConfig) {
    eleventyConfig.addPassthroughCopy("src/images");
    eleventyConfig.addPassthroughCopy("src/downloads");
    eleventyConfig.addPassthroughCopy("src/assets");
    return {
        dir: {
            input: "src",
            output: "_site",
            includes: "_includes",
            data: "_data"
        }
    };
};
