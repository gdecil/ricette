const express = require('express');
const router = express.Router();
const scrapeController = require('../controllers/scrapeController');

// Start scraping job
router.post('/', scrapeController.startScraping);

// Get job status
router.get('/job/:id', scrapeController.getJobStatus);

module.exports = router;