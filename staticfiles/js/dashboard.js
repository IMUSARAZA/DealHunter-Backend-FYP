// Dashboard JavaScript
$(document).ready(function() {
    // Toggle sidebar on mobile
    $('.navbar-toggler').on('click', function() {
        $('.sidebar-nav').slideToggle();
    });
    
    // Auto-refresh running jobs on dashboard
    function refreshRunningJobs() {
        $('.job-row').each(function() {
            const row = $(this);
            if (row.find('.badge').text().trim() === 'Running') {
                const jobId = row.data('job-id');
                if (jobId) {
                    $.ajax({
                        url: `/dashboard/job/${jobId}/status/`,
                        type: 'GET',
                        dataType: 'json',
                        success: function(data) {
                            // Update status
                            let statusHtml = '';
                            let rowClass = '';
                            
                            if (data.status === 'pending') {
                                statusHtml = '<span class="badge bg-secondary">Pending</span>';
                            } else if (data.status === 'running') {
                                statusHtml = '<span class="badge bg-warning">Running</span>';
                                rowClass = 'table-warning';
                            } else if (data.status === 'completed') {
                                statusHtml = '<span class="badge bg-success">Completed</span>';
                                rowClass = 'table-success';
                            } else if (data.status === 'failed') {
                                statusHtml = '<span class="badge bg-danger">Failed</span>';
                                rowClass = 'table-danger';
                            }
                            
                            row.find('td:nth-child(3)').html(statusHtml);
                            
                            // Update deals count if available
                            if (data.deals_scraped) {
                                row.find('td:nth-child(5)').text(data.deals_scraped);
                            }
                            
                            // Update row class
                            row.removeClass('table-warning table-success table-danger').addClass(rowClass);
                            
                            // If status changed to completed or failed, reload after a delay
                            if (data.status === 'completed' || data.status === 'failed') {
                                setTimeout(function() {
                                    location.reload();
                                }, 3000);
                            }
                        }
                    });
                }
            }
        });
    }
    
    // Set job-id data attribute for all job rows
    $('.job-row').each(function() {
        const jobId = $(this).find('a').attr('href').split('/').filter(Boolean).pop();
        $(this).data('job-id', jobId);
    });
    
    // Start refreshing running jobs if any exist
    const hasRunningJobs = $('.job-row .badge:contains("Running")').length > 0;
    if (hasRunningJobs) {
        setInterval(refreshRunningJobs, 10000); // Refresh every 10 seconds
    }
    
    // Initialize any tooltips
    $('[data-bs-toggle="tooltip"]').tooltip();
    
    // Initialize date-time pickers
    if ($.fn.datetimepicker) {
        $('.datetimepicker').datetimepicker({
            format: 'YYYY-MM-DD HH:mm',
            icons: {
                time: 'fas fa-clock',
                date: 'fas fa-calendar',
                up: 'fas fa-arrow-up',
                down: 'fas fa-arrow-down',
                previous: 'fas fa-chevron-left',
                next: 'fas fa-chevron-right',
                today: 'fas fa-calendar-check',
                clear: 'fas fa-trash',
                close: 'fas fa-times'
            }
        });
    }
    
    // Scroll to bottom of log container
    const logContainer = document.querySelector('.log-container');
    if (logContainer) {
        logContainer.scrollTop = logContainer.scrollHeight;
    }
});